# /app/jenkins_client.py
# -*- coding: utf-8 -*-
"""
Jenkins REST API Client (Read/Download 중심)
- Jenkins 루트(base_url)에서 Job(프로젝트) 목록 조회
- Job URL에서 빌드/아티팩트 목록 조회
- 특정 Build의 SCM 메타(changeSet/revision/branch/commit) 추출
- 필요 시 job config.xml에서 SCM URL/branch 추출(권한이 있을 때만)

인증
- Basic Auth: username + API token

주의
- GET 기반 조회/다운로드만 사용
- Folder Job 하위 jobs 재귀 조회 지원
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import time
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _join_url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    path = (path or "").lstrip("/")
    return f"{base}/{path}" if base else path


def _as_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _as_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _norm_str(x: Any) -> str:
    return str(x).strip() if isinstance(x, (str, int)) else ""


def _first_nonempty(*vals: Any) -> str:
    for v in vals:
        s = _norm_str(v)
        if s:
            return s
    return ""


# -----------------------------------------------------------------------------
# SCM extractor
# -----------------------------------------------------------------------------
def extract_scm_meta(build_json: dict) -> dict:
    """Jenkins build api/json에서 SCM(Git/SVN) 메타를 최대한 추출

    반환 예
      {
        "scm": "git",
        "git_commit": "<sha1>",
        "git_branch": "origin/main",
        "repo_urls": ["https://..."],
        "changes": [{"commit": "...", "msg": "...", "author": "..."}]
      }
      {
        "scm": "svn",
        "svn_revision": 12345,
        "repo_urls": ["https://..."]
      }
    """
    meta: Dict[str, Any] = {}
    if not isinstance(build_json, dict):
        return meta

    def set_once(k: str, v: Any) -> None:
        if v is None:
            return
        if isinstance(v, str) and not v.strip():
            return
        if k not in meta or meta.get(k) in (None, ""):
            meta[k] = v

    def add_repo_url(u: str) -> None:
        u = (u or "").strip()
        if not u:
            return
        meta.setdefault("repo_urls", [])
        if u not in meta["repo_urls"]:
            meta["repo_urls"].append(u)

    actions = _as_list(build_json.get("actions"))
    params: Dict[str, Any] = {}

    # 0) actions.parameters 수집
    for a in actions:
        a = _as_dict(a)
        for p in _as_list(a.get("parameters")):
            p = _as_dict(p)
            n = _norm_str(p.get("name"))
            if not n:
                continue
            params[n] = p.get("value")

    # 1) parameters 기반 빠른 추출 (Pipeline/Multibranch에서 자주 존재)
    br = _first_nonempty(params.get("BRANCH_NAME"), params.get("GIT_BRANCH"), params.get("branch"))
    if br:
        set_once("scm", "git")
        set_once("git_branch", br)

    sha = _first_nonempty(
        params.get("GIT_COMMIT"),
        params.get("SCM_REVISION"),
        params.get("COMMIT"),
        params.get("commit"),
    )
    if sha:
        set_once("scm", "git")
        set_once("git_commit", sha)

    svn_rev = params.get("SVN_REVISION") or params.get("SVNREV") or params.get("REVISION")
    if isinstance(svn_rev, int):
        set_once("scm", "svn")
        set_once("svn_revision", svn_rev)
    elif isinstance(svn_rev, str) and svn_rev.strip().isdigit():
        set_once("scm", "svn")
        set_once("svn_revision", int(svn_rev.strip()))

    # 2) actions에서 Git 플러그인/빌드 데이터 구조 추출
    for a in actions:
        a = _as_dict(a)

        # git BuildData: lastBuiltRevision / buildsByBranchName
        lbr = _as_dict(a.get("lastBuiltRevision"))
        if lbr:
            set_once("scm", "git")
            set_once("git_commit", _first_nonempty(lbr.get("SHA1"), lbr.get("sha1"), lbr.get("commit")))
            branches = _as_list(lbr.get("branch"))
            for b in branches:
                b = _as_dict(b)
                n = _norm_str(b.get("name"))
                if n:
                    set_once("git_branch", n)
                    break

        bbbn = _as_dict(a.get("buildsByBranchName"))
        if bbbn:
            set_once("scm", "git")
            for k in bbbn.keys():
                if isinstance(k, str) and k:
                    set_once("git_branch", k)
                    break
            for v in bbbn.values():
                v = _as_dict(v)
                rv = _as_dict(v.get("revision"))
                if rv:
                    set_once("git_commit", _first_nonempty(rv.get("SHA1"), rv.get("sha1")))
                break

        rv = _as_dict(a.get("revision"))
        if rv:
            set_once("scm", meta.get("scm") or "git")
            set_once("git_commit", _first_nonempty(rv.get("SHA1"), rv.get("sha1"), rv.get("commit")))

        b = _as_dict(a.get("branch"))
        if b:
            n = _norm_str(b.get("name"))
            if n:
                set_once("scm", meta.get("scm") or "git")
                set_once("git_branch", n)

        for key in ("remoteUrls", "remoteUrl", "remote", "url", "repositoryUrl", "repoUrl"):
            val = a.get(key)
            if isinstance(val, str):
                add_repo_url(val)
            elif isinstance(val, list):
                for x in val:
                    if isinstance(x, str):
                        add_repo_url(x)

        rev = a.get("revision") or a.get("rev") or a.get("Revision")
        if isinstance(rev, int):
            set_once("scm", "svn")
            set_once("svn_revision", rev)
        elif isinstance(rev, str) and rev.strip().isdigit():
            set_once("scm", "svn")
            set_once("svn_revision", int(rev.strip()))

        for r in _as_list(a.get("revisions")):
            r = _as_dict(r)
            rv2 = r.get("revision")
            if isinstance(rv2, int):
                set_once("scm", "svn")
                set_once("svn_revision", rv2)
            elif isinstance(rv2, str) and rv2.strip().isdigit():
                set_once("scm", "svn")
                set_once("svn_revision", int(rv2.strip()))

    # 3) changeSet 기반(가장 보편)
    changes_out: List[Dict[str, Any]] = []
    cs = _as_dict(build_json.get("changeSet"))
    items = _as_list(cs.get("items"))
    for it in items[:50]:
        it = _as_dict(it)
        cid = _first_nonempty(it.get("commitId"), it.get("commit"), it.get("id"))
        if cid:
            set_once("scm", meta.get("scm") or "git")
            set_once("git_commit", meta.get("git_commit") or cid)

        rv3 = it.get("revision")
        if isinstance(rv3, int):
            set_once("scm", meta.get("scm") or "svn")
            set_once("svn_revision", meta.get("svn_revision") or rv3)
        elif isinstance(rv3, str) and rv3.strip().isdigit():
            set_once("scm", meta.get("scm") or "svn")
            set_once("svn_revision", meta.get("svn_revision") or int(rv3.strip()))

        changes_out.append(
            {
                "commit": cid or "",
                "msg": _norm_str(it.get("msg") or it.get("comment") or it.get("message")),
                "author": _norm_str(_as_dict(it.get("author")).get("fullName") or it.get("author") or ""),
                "timestamp": it.get("timestamp"),
            }
        )
    if changes_out:
        meta["changes"] = changes_out

    # 4) top-level fields fallback
    set_once("git_branch", build_json.get("branch") or build_json.get("branchName"))
    scm = _as_dict(build_json.get("scm"))
    if scm:
        add_repo_url(_first_nonempty(scm.get("url"), scm.get("remote")))
        
    # -----------------------------------------------------------------
    # Derived convenience fields (GUI/SCM helpers에서 공통키로 활용)
    # -----------------------------------------------------------------
    if meta.get("git_branch") and not meta.get("scm_branch"):
        meta["scm_branch"] = meta.get("git_branch")
    if meta.get("git_commit") and not meta.get("scm_revision"):
        meta["scm_revision"] = meta.get("git_commit")
    if meta.get("svn_revision") and not meta.get("scm_revision"):
        meta["scm_revision"] = meta.get("svn_revision")
    if meta.get("scm") and not meta.get("scm_type"):
        meta["scm_type"] = meta.get("scm")

    return meta


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------
@dataclass
class JenkinsJob:
    name: str
    url: str
    color: Optional[str] = None
    class_name: Optional[str] = None


@dataclass
class JenkinsBuildInfo:
    number: int
    result: Optional[str] = None
    timestamp: Optional[int] = None
    url: Optional[str] = None
    building: Optional[bool] = None
    duration: Optional[int] = None


@dataclass
class JenkinsArtifact:
    fileName: str
    relativePath: str
    url: str


# -----------------------------------------------------------------------------
# Base client (shared)
# -----------------------------------------------------------------------------
class _BaseJenkinsClient:
    def __init__(
        self,
        base_or_job_url: str,
        username: str,
        api_token: str,
        timeout_sec: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        self.base_or_job_url = (base_or_job_url or "").strip().rstrip("/")
        self.username = (username or "").strip()
        self.api_token = (api_token or "").strip()
        self.timeout_sec = int(timeout_sec or 30)
        self.verify_ssl = bool(verify_ssl)

    def _auth_req(self, url: str, accept: str = "application/json") -> urllib.request.Request:
        token_raw = f"{self.username}:{self.api_token}".encode("utf-8")
        token_b64 = base64.b64encode(token_raw).decode("ascii")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {token_b64}")
        req.add_header("Accept", accept)
        return req

    def _context(self):
        if self.verify_ssl:
            return None
        if str(self.base_or_job_url).lower().startswith("https://"):
            return ssl._create_unverified_context()  # noqa: SLF001
        return None

    def _open_bytes(self, req: urllib.request.Request) -> bytes:
        ctx = self._context()
        with urllib.request.urlopen(req, timeout=self.timeout_sec, context=ctx) as resp:
            return resp.read()

    def _open_json(self, url: str) -> dict:
        req = self._auth_req(url, accept="application/json")
        raw = self._open_bytes(req)
        try:
            return json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            return {}

    def _open_text(self, url: str, accept: str = "text/plain") -> str:
        req = self._auth_req(url, accept=accept)
        raw = self._open_bytes(req)
        return raw.decode("utf-8", errors="ignore")


# -----------------------------------------------------------------------------
# Jenkins root client
# -----------------------------------------------------------------------------
class JenkinsServerClient(_BaseJenkinsClient):
    def __init__(
        self,
        base_url: str,
        username: str,
        api_token: str,
        timeout_sec: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(base_url, username, api_token, timeout_sec=timeout_sec, verify_ssl=verify_ssl)

    def _is_folder(self, class_name: str | None) -> bool:
        if not class_name:
            return False
        c = class_name.lower()
        return c.endswith(".folder") or c.endswith("folder")

    def list_jobs(self, recursive: bool = True, max_depth: int = 2) -> List[JenkinsJob]:
        max_depth = max(0, int(max_depth))
        out: List[JenkinsJob] = []

        def _walk(jenkins_url: str, prefix: str, depth: int) -> None:
            api = _join_url(jenkins_url, "api/json?tree=jobs[name,url,color,_class]")
            data = self._open_json(api)
            for j in _as_list(data.get("jobs")):
                j = _as_dict(j)
                name = _norm_str(j.get("name"))
                url = _norm_str(j.get("url"))
                if not name or not url:
                    continue
                full_name = f"{prefix}{name}" if not prefix else f"{prefix}/{name}"
                out.append(
                    JenkinsJob(
                        name=full_name,
                        url=url,
                        color=_norm_str(j.get("color")) or None,
                        class_name=_norm_str(j.get("_class")) or None,
                    )
                )
                if recursive and depth < max_depth and self._is_folder(_norm_str(j.get("_class"))):
                    _walk(url, full_name, depth + 1)

        _walk(self.base_or_job_url, "", 0)
        uniq: Dict[str, JenkinsJob] = {}
        for j in out:
            uniq[j.url] = j
        return list(uniq.values())


# -----------------------------------------------------------------------------
# Jenkins job client
# -----------------------------------------------------------------------------
class JenkinsClient(_BaseJenkinsClient):
    def __init__(
        self,
        job_url: str,
        username: str,
        api_token: str,
        timeout_sec: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(job_url, username, api_token, timeout_sec=timeout_sec, verify_ssl=verify_ssl)
        self.job_url = (job_url or "").strip().rstrip("/") + "/"

    def list_artifacts(self, build_selector: str = "lastSuccessfulBuild") -> Tuple[JenkinsBuildInfo, List[JenkinsArtifact]]:
        selector = str(build_selector).strip()
        api = _join_url(
            self.job_url,
            f"{selector}/api/json?tree=number,result,timestamp,url,building,duration,artifacts[fileName,relativePath],_class",
        )
        data = self._open_json(api)

        b = JenkinsBuildInfo(
            number=int(data.get("number") or -1),
            result=_norm_str(data.get("result")) or None,
            timestamp=data.get("timestamp"),
            url=_norm_str(data.get("url")) or None,
            building=bool(data.get("building")) if ("building" in data) else None,
            duration=int(data.get("duration")) if isinstance(data.get("duration"), (int, float)) else None,
        )
        artifacts: List[JenkinsArtifact] = []
        for a in _as_list(data.get("artifacts")):
            a = _as_dict(a)
            fn = _norm_str(a.get("fileName"))
            rp = _norm_str(a.get("relativePath"))
            if not fn or not rp:
                continue
            artifacts.append(
                JenkinsArtifact(
                    fileName=fn,
                    relativePath=rp,
                    url=_join_url(self.job_url, f"{selector}/artifact/{urllib.parse.quote(rp)}"),
                )
            )
        return b, artifacts

    def get_build_json(self, build_selector: str = "lastSuccessfulBuild", tree: str | None = None) -> dict:
        selector = str(build_selector).strip()
        api = _join_url(self.job_url, f"{selector}/api/json")
        if tree:
            sep = "&" if "?" in api else "?"
            api = f"{api}{sep}tree={urllib.parse.quote(tree, safe=',[]*:_')}"
        return self._open_json(api)

    def get_job_config_xml(self) -> str:
        try:
            url = _join_url(self.job_url, "config.xml")
            return self._open_text(url, accept="application/xml")
        except Exception:
            return ""

    @staticmethod
    def extract_scm_from_config_xml(xml_text: str) -> dict:
        out: Dict[str, Any] = {}
        if not xml_text or not isinstance(xml_text, str):
            return out
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return out

        repo_urls: List[str] = []
        git_branch = ""

        def add_url(u: str) -> None:
            u = (u or "").strip()
            if u and u not in repo_urls:
                repo_urls.append(u)

        for url_el in root.findall(".//scm//userRemoteConfigs//hudson.plugins.git.UserRemoteConfig//url"):
            if url_el.text:
                add_url(url_el.text)

        for br_el in root.findall(".//scm//branches//hudson.plugins.git.BranchSpec//name"):
            if br_el.text and not git_branch:
                git_branch = br_el.text.strip()

        for rem_el in root.findall(".//scm//locations//hudson.scm.SubversionSCM_-ModuleLocation//remote"):
            if rem_el.text:
                add_url(rem_el.text)

        if repo_urls:
            out["repo_urls"] = repo_urls
        if git_branch:
            out["scm"] = out.get("scm") or "git"
            out["git_branch"] = git_branch
        return out

    def get_scm_meta(self, build_selector: str = "lastSuccessfulBuild") -> dict:
        tree = (
            "number,result,timestamp,url,"
            "actions[parameters[name,value],lastBuiltRevision[SHA1,branch[name]],buildsByBranchName,"
            "revision[SHA1,sha1],branch[name],remoteUrls,url,remoteUrl,repositoryUrl,repoUrl,revisions[revision]],"
            "changeSet[items[commitId,revision,msg,comment,timestamp,author[fullName]]]"
        )
        try:
            data = self.get_build_json(build_selector=build_selector, tree=tree)
        except Exception:
            data = self.get_build_json(build_selector=build_selector, tree=None)

        meta = extract_scm_meta(data)

        if not meta.get("repo_urls"):
            cfg_xml = self.get_job_config_xml()
            cfg_meta = self.extract_scm_from_config_xml(cfg_xml)
            if cfg_meta.get("repo_urls"):
                meta.setdefault("repo_urls", cfg_meta["repo_urls"])
            if cfg_meta.get("git_branch") and not meta.get("git_branch"):
                meta["git_branch"] = cfg_meta["git_branch"]
            if cfg_meta.get("scm") and not meta.get("scm"):
                meta["scm"] = cfg_meta["scm"]

        return meta

    def filter_artifacts(self, artifacts: List[JenkinsArtifact], patterns: List[str]) -> List[JenkinsArtifact]:
        pats = [p.strip() for p in (patterns or []) if p and p.strip()]
        if not pats:
            return artifacts

        out: List[JenkinsArtifact] = []
        for a in artifacts:
            rp = (a.relativePath or "").replace("\\", "/")
            if any(fnmatch.fnmatch(rp, pat) for pat in pats):
                out.append(a)
        return out

    def download_artifact(self, artifact: JenkinsArtifact, dst_path: str, chunk_size: int = 1024 * 256) -> None:
        """Download one artifact to dst_path.
        - Atomic write (*.part then replace)
        - Retry on transient errors
        """
        if not artifact or not getattr(artifact, "url", ""):
            raise ValueError("artifact url missing")

        url = artifact.url
        dst = Path(str(dst_path))
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part") if dst.suffix else Path(str(dst) + ".part")

        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                req = self._auth_req(url, accept="application/octet-stream")
                ctx = self._context()
                with urllib.request.urlopen(req, timeout=self.timeout_sec, context=ctx) as resp:
                    with tmp.open("wb") as f:
                        while True:
                            chunk = resp.read(int(chunk_size))
                            if not chunk:
                                break
                            f.write(chunk)
                os.replace(str(tmp), str(dst))
                return
            except Exception as e:
                last_err = e
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
                if attempt < 3:
                    time.sleep(0.5 * attempt)
                    continue
                raise