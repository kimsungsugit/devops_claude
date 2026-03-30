# /app/gui/tabs/__init__.py
from . import dashboard
from . import editor
from . import analysis_views
from . import knowledge
from . import chat  # 채팅 탭 추가
from . import scm  # SCM 탭 추가

from . import jenkins_reports  # Jenkins 리포트 탭 추가

__all__ = ["dashboard", "editor", "analysis_views", "knowledge", "chat", "scm", "jenkins_reports"]
