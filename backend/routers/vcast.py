"""Auto-generated router: vcast"""
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
from pathlib import Path
from datetime import datetime

from backend.schemas import (
    VCastGenerateExcelRequest,
    VCastParseRequest,
    VCastProcessJenkinsRequest,
)
from backend.helpers import _resolve_cached_build_root
from backend.services.vcast_parser import (
    VectorCASTParser,
    VCASTVersion,
    ReportType,
    parse_vcast_report,
    MetricsBank,
)
from backend.services.vcast_excel_generator import generate_testcase_excel, generate_metrics_excel
from backend.services.paths import safe_resolve_under

repo_root = Path(__file__).resolve().parents[2]

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/vcast/parse")
async def vcast_parse(
    file: UploadFile = File(...),
    report_type: str = Query("TestCaseData"),
    version: str = Query("Ver2025"),
) -> Dict[str, Any]:
    """VectorCAST HTML 리포트 파일 파싱"""
    
    try:
        # 리포트 타입 확인
        report_type_map = {
            "TestCaseData": ReportType.TestCaseData,
            "ExecutionResult": ReportType.ExecutionResult,
            "Metrics": ReportType.Metrics,
            "AggregateCoverage": ReportType.AggregateCoverage,
        }
        report_type_enum = report_type_map.get(report_type)
        if not report_type_enum:
            raise HTTPException(status_code=400, detail=f"Invalid report type: {report_type}")
        
        # 버전 확인
        version_map = {
            "Ver2021": VCASTVersion.Ver2021,
            "Ver2024": VCASTVersion.Ver2024,
            "Ver2025": VCASTVersion.Ver2025,
        }
        version_enum = version_map.get(version, VCASTVersion.Ver2025)
        
        # 임시 파일에 저장
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)
        
        try:
            # 리포트 파싱
            parsed_result = parse_vcast_report(tmp_path, report_type_enum, version_enum)
            
            # Metrics 또는 AggregateCoverage인 경우
            if isinstance(parsed_result, MetricsBank):
                metrics_bank = parsed_result
                result = {
                    "ok": True,
                    "report_type": report_type,
                    "environment": metrics_bank.environment,
                    "statement_units": len(metrics_bank.statement_data),
                    "functions_units": len(metrics_bank.functions_data),
                    "sub_functions": len(metrics_bank.sub_functions),
                }
                
                # Statement 데이터 변환
                if metrics_bank.statement_data:
                    statement_data = {}
                    for unit_name, bank in metrics_bank.statement_data.items():
                        statement_data[unit_name] = {
                            "items": [
                                {
                                    "id": item.id,
                                    "subprogram": item.subprogram,
                                    "complexity": item.complexity,
                                    "statements": {
                                        "count": item.statements.count if item.statements else 0,
                                        "total": item.statements.total if item.statements else 0,
                                        "coverage": item.statements.coverage if item.statements else "",
                                    } if item.statements else None,
                                    "branches": {
                                        "count": item.branches.count if item.branches else 0,
                                        "total": item.branches.total if item.branches else 0,
                                        "coverage": item.branches.coverage if item.branches else "",
                                    } if item.branches else None,
                                    "is_function": item.is_function,
                                    "functions_call": {
                                        "count": item.functions_call.count if item.functions_call else 0,
                                        "total": item.functions_call.total if item.functions_call else 0,
                                        "coverage": item.functions_call.coverage if item.functions_call else "",
                                    } if item.functions_call else None,
                                }
                                for item in bank.dic_data.values()
                                if hasattr(item, 'subprogram')
                            ]
                        }
                    result["statement_data"] = statement_data
                
                # Functions 데이터 변환
                if metrics_bank.functions_data:
                    functions_data = {}
                    for unit_name, bank in metrics_bank.functions_data.items():
                        functions_data[unit_name] = {
                            "items": [
                                {
                                    "id": item.id,
                                    "subprogram": item.subprogram,
                                    "complexity": item.complexity,
                                    "functions": {
                                        "count": item.functions.count if item.functions else 0,
                                        "total": item.functions.total if item.functions else 0,
                                        "coverage": item.functions.coverage if item.functions else "",
                                    } if item.functions else None,
                                    "functions_call": {
                                        "count": item.functions_call.count if item.functions_call else 0,
                                        "total": item.functions_call.total if item.functions_call else 0,
                                        "coverage": item.functions_call.coverage if item.functions_call else "",
                                    } if item.functions_call else None,
                                }
                                for item in bank.dic_data.values()
                                if hasattr(item, 'subprogram')
                            ]
                        }
                    result["functions_data"] = functions_data
                
                # Sub functions 데이터 변환
                if metrics_bank.sub_functions:
                    sub_functions_data = {}
                    for module_name, items in metrics_bank.sub_functions.items():
                        sub_functions_data[module_name] = [
                            {
                                "order": item.order,
                                "name": item.name,
                                "executed": item.executed,
                            }
                            for item in items
                        ]
                    result["sub_functions"] = sub_functions_data
                
                return result
            
            # TestCaseData 또는 ExecutionResult인 경우
            else:
                tcbank = parsed_result
                # 결과를 딕셔너리로 변환
                result = {
                    "ok": True,
                    "report_type": report_type,
                    "environment": tcbank.environment,
                    "component_name": tcbank.component_name,
                    "test_count": tcbank.test_count,
                    "passed_count": tcbank.passed_count,
                    "input_names": tcbank.input_names,
                    "exp_result_names": tcbank.exp_result_names,
                    "act_result_names": tcbank.act_result_names,
                    "max_input_count": tcbank.max_input_count,
                    "max_exp_result_count": tcbank.max_exp_result_count,
                    "max_act_result_count": tcbank.max_act_result_count,
                }
                
                # 테스트 케이스 데이터 변환
                if tcbank.test_cases:
                    test_cases_data = {}
                    for tc_name, tc_items in tcbank.test_cases.items():
                        test_cases_data[tc_name] = [
                            {
                                "header": {
                                    "component_name": item.header.component_name,
                                    "unit_name": item.header.unit_name,
                                    "test_case_name": item.header.test_case_name,
                                    "test_case_index": item.header.test_case_index,
                                },
                                "input_data": item.input_data,
                                "expected_result": item.expected_result,
                                "user_code": item.user_code,
                                "description": item.description,
                            }
                            for item in tc_items
                        ]
                    result["test_cases"] = test_cases_data
                
                # 테스트 결과 데이터 변환
                if tcbank.test_results:
                    test_results_data = {}
                    for tc_name, tr_items in tcbank.test_results.items():
                        test_results_data[tc_name] = [
                            {
                                "header": {
                                    "component_name": item.header.component_name,
                                    "unit_name": item.header.unit_name,
                                    "test_case_name": item.header.test_case_name,
                                    "test_case_index": item.header.test_case_index,
                                },
                                "passed": item.passed,
                                "actual_result": {k: {"actual": v[0], "expected": v[1]} 
                                                for k, v in item.actual_result.items()},
                                "user_code": item.user_code,
                            }
                            for item in tr_items
                        ]
                    result["test_results"] = test_results_data
                
                return result
        finally:
            # 임시 파일 삭제
            try:
                tmp_path.unlink()
            except Exception:
                pass
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {str(e)}")


@router.post("/api/vcast/generate-excel")
def vcast_generate_excel(req: VCastGenerateExcelRequest) -> FileResponse:
    """파싱된 데이터로 Excel 리포트 생성"""
    try:
        if not isinstance(req.parsed_data, dict):
            raise HTTPException(status_code=400, detail="parsed_data must be an object")
        mode = str(req.mode or "TestCase")
        if mode == "TestReport":
            mode = "TestCase"
        # 출력 디렉토리 생성
        output_dir = repo_root / "reports" / "vcast_excel"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 파일명 생성
        if req.output_filename:
            filename = req.output_filename
            if not filename.endswith(".xlsx"):
                filename += ".xlsx"
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"vcast_report_{ts}.xlsx"
        
        output_path = output_dir / filename
        
        # Metrics 리포트인 경우
        if mode == "Metrics" or "statement_data" in req.parsed_data or "functions_data" in req.parsed_data:
            from backend.services.vcast_parser import (
                MetricsBank,
                MatixDataBank,
                MatricStatementItem,
                MatricFunCallItem,
                CoverageItem,
                MatricsType,
            )
            
            metrics_bank = MetricsBank()
            metrics_bank.environment = req.parsed_data.get("environment", "")
            
            # Statement 데이터 재구성
            if "statement_data" in req.parsed_data:
                for unit_name, unit_data in req.parsed_data["statement_data"].items():
                    bank = MatixDataBank(MatricsType.Statement, unit_name)
                    for item_data in unit_data.get("items", []):
                        item = MatricStatementItem(
                            id=item_data.get("id", ""),
                            unit_name=unit_name,
                            subprogram=item_data.get("subprogram", ""),
                            complexity=item_data.get("complexity", 0),
                        )
                        if item_data.get("statements"):
                            stmt = item_data["statements"]
                            item.statements = CoverageItem(f"{stmt['count']} / {stmt['total']} ({stmt.get('coverage', '')})")
                        if item_data.get("branches"):
                            br = item_data["branches"]
                            item.branches = CoverageItem(f"{br['count']} / {br['total']} ({br.get('coverage', '')})")
                        if item_data.get("functions_call"):
                            fc = item_data["functions_call"]
                            item.functions_call = CoverageItem(f"{fc['count']} / {fc['total']} ({fc.get('coverage', '')})")
                        item.is_function = item_data.get("is_function", False)
                        if item.is_valid:
                            bank.add(item)
                    metrics_bank.statement_data[unit_name] = bank
            
            # Functions 데이터 재구성
            if "functions_data" in req.parsed_data:
                for unit_name, unit_data in req.parsed_data["functions_data"].items():
                    bank = MatixDataBank(MatricsType.Functions, unit_name)
                    for item_data in unit_data.get("items", []):
                        item = MatricFunCallItem(
                            file_id=item_data.get("id", ""),
                            unit_name=unit_name,
                            subprogram=item_data.get("subprogram", ""),
                            complexity=item_data.get("complexity", 0),
                        )
                        if item_data.get("functions"):
                            func = item_data["functions"]
                            item.functions = CoverageItem(f"{func['count']} / {func['total']} ({func.get('coverage', '')})")
                        if item_data.get("functions_call"):
                            fc = item_data["functions_call"]
                            item.functions_call = CoverageItem(f"{fc['count']} / {fc['total']} ({fc.get('coverage', '')})")
                        if item.is_valid:
                            bank.add(item)
                    metrics_bank.functions_data[unit_name] = bank
            
            # Excel 생성
            if generate_metrics_excel(metrics_bank, output_path, req.unit_bank):
                return FileResponse(str(output_path), filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                raise HTTPException(status_code=500, detail="Metrics Excel generation failed")
        
        # TestCase/TestResult 리포트인 경우
        else:
            # TCBank 객체 재구성
            from backend.services.vcast_parser import TCBank, TestCaseItem, TestResultItem, VCastHeader
            
            tcbank = TCBank()
            tcbank.environment = req.parsed_data.get("environment", "")
            tcbank.component_name = req.parsed_data.get("component_name", "")
            tcbank.input_names = req.parsed_data.get("input_names", [])
            tcbank.exp_result_names = req.parsed_data.get("exp_result_names", [])
            tcbank.act_result_names = req.parsed_data.get("act_result_names", [])
            tcbank.max_input_count = req.parsed_data.get("max_input_count", 0)
            tcbank.max_exp_result_count = req.parsed_data.get("max_exp_result_count", 0)
            tcbank.max_act_result_count = req.parsed_data.get("max_act_result_count", 0)
            
            # 테스트 케이스 데이터 재구성
            test_cases = req.parsed_data.get("test_cases")
            if test_cases is not None and not isinstance(test_cases, dict):
                raise HTTPException(status_code=400, detail="test_cases must be an object")
            if isinstance(test_cases, dict):
                for tc_name, tc_items_data in test_cases.items():
                    tc_items = []
                    for item_data in tc_items_data or []:
                        if not isinstance(item_data, dict):
                            continue
                        header_data = item_data.get("header") or {}
                        header = VCastHeader(
                            component_name=header_data.get("component_name", ""),
                            unit_name=header_data.get("unit_name", ""),
                            test_case_name=header_data.get("test_case_name", ""),
                            test_case_index=header_data.get("test_case_index", ""),
                            filename="",
                        )
                        tc_item = TestCaseItem(
                            header=header,
                            input_data=item_data.get("input_data", {}),
                            expected_result=item_data.get("expected_result", {}),
                            user_code=item_data.get("user_code", {}),
                            description=item_data.get("description", ""),
                        )
                        tc_items.append(tc_item)
                    tcbank.test_cases[tc_name] = tc_items
            
            # 테스트 결과 데이터 재구성
            test_results = req.parsed_data.get("test_results")
            if test_results is not None and not isinstance(test_results, dict):
                raise HTTPException(status_code=400, detail="test_results must be an object")
            if isinstance(test_results, dict):
                for tc_name, tr_items_data in test_results.items():
                    tr_items = []
                    for item_data in tr_items_data or []:
                        if not isinstance(item_data, dict):
                            continue
                        header_data = item_data.get("header") or {}
                        header = VCastHeader(
                            component_name=header_data.get("component_name", ""),
                            unit_name=header_data.get("unit_name", ""),
                            test_case_name=header_data.get("test_case_name", ""),
                            test_case_index=header_data.get("test_case_index", ""),
                            filename="",
                        )
                        actual_result = {}
                        for k, v in (item_data.get("actual_result") or {}).items():
                            if isinstance(v, dict):
                                actual_result[k] = (v.get("actual"), v.get("expected"))
                            elif isinstance(v, (list, tuple)) and len(v) >= 2:
                                actual_result[k] = (v[0], v[1])
                            else:
                                actual_result[k] = (v, "")
                        
                        tr_item = TestResultItem(
                            header=header,
                            passed=item_data.get("passed", False),
                            actual_result=actual_result,
                            user_code=item_data.get("user_code", []),
                        )
                        tr_items.append(tr_item)
                    tcbank.test_results[tc_name] = tr_items
            
            # Excel 생성
            if generate_testcase_excel(tcbank, output_path, mode):
                return FileResponse(str(output_path), filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                raise HTTPException(status_code=500, detail="Excel generation failed")
    
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        raise HTTPException(status_code=500, detail=f"Excel generation error: {str(e)}")


@router.post("/api/vcast/process-jenkins")
def vcast_process_jenkins(req: VCastProcessJenkinsRequest) -> Dict[str, Any]:
    """젠킨스 아티팩트에서 VectorCAST 리포트 찾아 처리"""
    try:
        # 젠킨스 빌드 루트 찾기
        build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
        if not build_root:
            raise HTTPException(status_code=404, detail="Cached build not found")
        
        # 리포트 파일 패턴
        patterns = {
            "TestCaseData": "*TestCaseDataReport.html",
            "ExecutionResult": "*ExecutionResultReport.html",
            "Metrics": "*MetricsReport.html",
            "AggregateCoverage": "*AggregateCoverageReport.html",
        }
        
        pattern = patterns.get(req.report_type, "*TestCaseDataReport.html")
        
        # 리포트 파일 찾기
        report_files = list(build_root.rglob(pattern))
        if not report_files:
            return {
                "ok": False,
                "message": f"No {req.report_type} report files found",
                "files": [],
            }
        
        # 첫 번째 파일 파싱
        report_file = report_files[0]
        
        # 리포트 타입 확인
        report_type_map = {
            "TestCaseData": ReportType.TestCaseData,
            "ExecutionResult": ReportType.ExecutionResult,
        }
        report_type = report_type_map.get(req.report_type)
        if not report_type:
            return {
                "ok": False,
                "message": f"Unsupported report type: {req.report_type}",
            }
        
        # 버전 확인
        version_map = {
            "Ver2021": VCASTVersion.Ver2021,
            "Ver2024": VCASTVersion.Ver2024,
            "Ver2025": VCASTVersion.Ver2025,
        }
        version = version_map.get(req.version, VCASTVersion.Ver2025)
        
        # 리포트 파싱
        tcbank = parse_vcast_report(report_file, report_type, version)
        
        # 결과 반환
        return {
            "ok": True,
            "file": str(report_file.relative_to(build_root)),
            "environment": tcbank.environment,
            "component_name": tcbank.component_name,
            "test_count": tcbank.test_count,
            "passed_count": tcbank.passed_count,
            "files_found": [str(f.relative_to(build_root)) for f in report_files],
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Process error: {str(e)}")


@router.get("/api/vcast/reports")
def vcast_list_reports() -> Dict[str, Any]:
    """생성된 Excel 리포트 목록 조회"""
    try:
        reports_dir = repo_root / "reports" / "vcast_excel"
        if not reports_dir.exists():
            return {"ok": True, "reports": []}
        
        reports = []
        for file_path in sorted(reports_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
            reports.append({
                "filename": file_path.name,
                "size": file_path.stat().st_size,
                "created": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            })
        
        return {"ok": True, "reports": reports}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List error: {str(e)}")


@router.get("/api/vcast/reports/{filename}")
def vcast_download_report(filename: str) -> FileResponse:
    """생성된 Excel 리포트 다운로드"""
    try:
        reports_dir = repo_root / "reports" / "vcast_excel"
        file_path = safe_resolve_under(reports_dir, filename)
        
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Report file not found")
        
        return FileResponse(
            str(file_path),
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")


