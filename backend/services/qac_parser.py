"""QAC HIS Metrics Report 파서

TResultParser C# 프로그램의 QACDataManager 로직을 Python으로 포팅한 QAC 리포트 파서입니다.
PRQA (Old Version) 및 Helix QAC (New Version) 리포트를 파싱합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


class MatrixItem(Enum):
    """Matrix 항목"""
    CALLS = 0  # STCAL
    RETURN = 1  # STM19
    V_G = 2  # STCYC
    PATH = 3  # STPTH
    LEVEL = 4  # STMIF
    STMT = 5  # STST3
    PARAM = 6  # STPAR
    GOTO = 7  # STGTO
    CALLING = 8  # STM29
    Count = 9


@dataclass
class MatrixSpec:
    """Matrix 스펙"""
    matrix_type: MatrixItem
    list_spec: List[int] = field(default_factory=list)
    
    @property
    def spec_count(self) -> int:
        return len(self.list_spec)
    
    def clear(self, data_only: bool = False) -> None:
        """스펙 초기화"""
        if self.spec_count == 0:
            return
        
        if data_only:
            for i in range(self.spec_count):
                self.list_spec[i] = 0
        else:
            self.list_spec.clear()


@dataclass
class HISItem:
    """HIS 아이템"""
    function_name: str = ""
    file_name: str = ""
    status: bool = False
    dic_values: Dict[MatrixItem, str] = field(default_factory=dict)
    
    @staticmethod
    def get_title(item: MatrixItem, name: bool) -> str:
        """Matrix 항목 제목 반환"""
        titles = {
            MatrixItem.CALLS: ("CALLS", "STCAL"),
            MatrixItem.RETURN: ("RETURN", "STM19"),
            MatrixItem.V_G: ("v(G)", "STCYC"),
            MatrixItem.PATH: ("PATH", "STPTH"),
            MatrixItem.LEVEL: ("LEVEL", "STMIF"),
            MatrixItem.STMT: ("STMT", "STST3"),
            MatrixItem.PARAM: ("PARAM", "STPAR"),
            MatrixItem.GOTO: ("GOTO", "STGTO"),
            MatrixItem.CALLING: ("CALLING", "STM29"),
        }
        if item in titles:
            return titles[item][0] if name else titles[item][1]
        return ""
    
    @staticmethod
    def split_string(data: str, delimiters: List[str]) -> List[str]:
        """문자열 분리"""
        if not data:
            return []
        
        pattern = "|".join(re.escape(d) for d in delimiters)
        parts = re.split(pattern, data)
        return [p.strip() for p in parts if p.strip()]
    
    def get_matrix_value(self, item: MatrixItem) -> str:
        """Matrix 값 반환"""
        return self.dic_values.get(item, "")
    
    def update_data(self, table_data: List[str]) -> bool:
        """테이블 데이터로부터 정보 업데이트"""
        self.status = False
        self.function_name = ""
        self.dic_values.clear()
        
        if not table_data or len(table_data) != 5:
            return False
        
        # 헤더 확인
        if "<h4>" not in table_data[0]:
            return False
        
        if "<table" not in table_data[1] or "</table>" not in table_data[4]:
            return False
        
        if "<tr><td" not in table_data[2] or "<tr><td" not in table_data[3]:
            return False
        
        # 함수 이름 추출
        self.function_name = self._get_function_name(table_data[0])
        if not self.function_name:
            return False
        
        # Matrix와 Value 추출
        list_matrix = self._split_table_data(True, table_data[2])
        list_value = self._split_table_data(False, table_data[3])
        
        if not list_matrix or not list_value or len(list_matrix) != len(list_value):
            return False
        
        # Matrix 항목 매핑
        for idx in range(1, len(list_matrix)):
            item = self._convert_matrix_item(list_matrix[idx])
            if item == MatrixItem.Count:
                return False
            
            self.dic_values[item] = list_value[idx]
        
        self.status = True
        return True

    def update_from_bs4(self, function_name: str, headers: List[str], values: List[str]) -> bool:
        self.status = False
        self.function_name = function_name or ""
        self.dic_values.clear()
        if not self.function_name or not headers or not values:
            return False
        if len(headers) != len(values):
            return False
        for idx in range(1, len(headers)):
            item = self._convert_matrix_item(headers[idx])
            if item == MatrixItem.Count:
                continue
            self.dic_values[item] = values[idx]
        self.status = True
        return True
    
    def _get_function_name(self, data: str) -> str:
        """함수 이름 추출"""
        start = data.find(":")
        end = data.find("</h4>")
        
        if start < 0 or end < 0:
            return ""
        
        return data[start + 1:end].strip()
    
    def _split_table_data(self, is_matrix: bool, data: str) -> Optional[List[str]]:
        """테이블 데이터 분리"""
        if (is_matrix and "Metric" not in data) or (not is_matrix and "Values" not in data):
            return None
        
        parts = self.split_string(data, ["<", ">"])
        result = []
        
        for part in parts:
            if (part.find("tr") >= 0 and part != "Metric") or part.find("td") >= 0:
                continue
            result.append(part)
        
        return result
    
    def _convert_matrix_item(self, caption: str) -> MatrixItem:
        """캡션을 MatrixItem으로 변환"""
        for item in MatrixItem:
            if item == MatrixItem.Count:
                continue
            title = self.get_title(item, True)
            if title and title in caption:
                return item
        
        return MatrixItem.Count


@dataclass
class QACDataManager:
    """QAC 데이터 매니저"""
    dic_spec: Dict[MatrixItem, MatrixSpec] = field(default_factory=dict)
    dic_spec_over_count: Dict[MatrixItem, MatrixSpec] = field(default_factory=dict)
    list_result: List[HISItem] = field(default_factory=list)
    
    # 라인 번호 상수
    LINENO_TITLE_OLD = 112
    LINENO_TITLE_NEW = 117
    LINENO_FILESTART_OLD = 121
    LINENO_FILESTART_NEW = 127
    
    def __post_init__(self):
        """초기화"""
        self._build_spec()
        self.clear()
    
    @staticmethod
    def get_matrix_list() -> List[MatrixItem]:
        """Matrix 항목 리스트 반환"""
        return [MatrixItem.V_G, MatrixItem.LEVEL, MatrixItem.CALLING, MatrixItem.CALLS]
    
    def read_file(self, old_version: bool, filepath: Path) -> bool:
        """QAC 리포트 파일 읽기"""
        self.clear()
        
        if not filepath.exists():
            return False

        if BeautifulSoup:
            if self._read_file_bs4(old_version, filepath):
                return True
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        matrix_filename = ""
        table_lines = []
        index = 0
        
        target_title_line = self.LINENO_TITLE_OLD if old_version else self.LINENO_TITLE_NEW
        target_file_start = self.LINENO_FILESTART_OLD if old_version else self.LINENO_FILESTART_NEW
        
        for line in lines:
            # 파일 타입 확인
            if index == target_title_line:
                if "<title>" not in line:
                    continue
                if old_version and "PRQA HIS Metrics Report" not in line:
                    return False
                if not old_version and "Helix QAC HIS Metrics Report" not in line:
                    return False
            
            # 파일 데이터 시작
            if index >= target_file_start:
                if "<h3>File" in line or "<h4>Function" in line:
                    if "<h3>File" in line:
                        matrix_filename = self._get_file_path(line)
                    table_lines = [line]
                elif "<table" in line or "<tr><td" in line:
                    table_lines.append(line)
                elif "</table>" in line:
                    table_lines.append(line)
                    
                    if len(table_lines) == 5:
                        his_item = HISItem()
                        if his_item.update_data(table_lines):
                            his_item.file_name = matrix_filename
                            self.list_result.append(his_item)
                            for matrix in self.get_matrix_list():
                                warn = self.check_warning_level(matrix, his_item.get_matrix_value(matrix))
                                self.update_spec_over_count(matrix, warn)
                    
                    table_lines = []
            
            index += 1
        
        return len(self.list_result) > 0

    def _read_file_bs4(self, old_version: bool, filepath: Path) -> bool:
        try:
            html = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else ""
        if old_version and "PRQA HIS Metrics Report" not in title:
            return False
        if not old_version and "Helix QAC HIS Metrics Report" not in title:
            return False
        current_file = ""
        for tag in soup.find_all(["h3", "h4"]):
            text = tag.get_text(strip=True)
            if tag.name == "h3" and text.startswith("File"):
                current_file = text.split(":", 1)[-1].strip()
                continue
            if tag.name != "h4" or "Function" not in text:
                continue
            function_name = text.split(":", 1)[-1].strip()
            table = tag.find_next("table")
            if not table:
                continue
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
            values = [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
            his_item = HISItem()
            if his_item.update_from_bs4(function_name, headers, values):
                his_item.file_name = current_file
                self.list_result.append(his_item)
                for matrix in self.get_matrix_list():
                    warn = self.check_warning_level(matrix, his_item.get_matrix_value(matrix))
                    self.update_spec_over_count(matrix, warn)
        return len(self.list_result) > 0
    
    def check_warning_level(self, matrix: MatrixItem, value: str) -> int:
        """경고 레벨 확인"""
        if matrix not in self.dic_spec or not value:
            return 0
        
        spec = self.dic_spec[matrix]
        if not spec or spec.spec_count == 0:
            return 0
        
        try:
            matrix_value = int(value)
        except ValueError:
            return 0
        
        # 역순으로 확인 (높은 레벨부터)
        for idx in range(spec.spec_count - 1, -1, -1):
            if matrix_value >= spec.list_spec[idx]:
                return idx + 1
        
        return 0
    
    def update_spec_over_count(self, item: MatrixItem, warning_level: int) -> None:
        """스펙 초과 카운트 업데이트"""
        if warning_level < 0 or item not in self.dic_spec_over_count:
            return
        
        spec = self.dic_spec_over_count[item]
        if warning_level <= spec.spec_count:
            spec.list_spec[warning_level - 1] = spec.list_spec[warning_level - 1] + 1
    
    def get_spec_string(self, matrix: MatrixItem, warn_level: int) -> str:
        """스펙 문자열 반환"""
        if matrix not in self.dic_spec or warn_level == 0:
            return ""
        
        spec = self.dic_spec[matrix]
        if warn_level > spec.spec_count:
            return ""
        
        threshold = spec.list_spec[warn_level - 1]
        return f"{HISItem.get_title(matrix, False)} >= {threshold}"
    
    def get_column_index_of_matrix_item(self, matrix: MatrixItem) -> int:
        """Matrix 항목의 컬럼 인덱스 반환"""
        matrix_list = self.get_matrix_list()
        default_col = 2
        
        for idx, item in enumerate(matrix_list):
            if item == matrix:
                return default_col + idx
        
        return -1
    
    def _get_file_path(self, org: str) -> str:
        """파일 경로 추출"""
        if not org or "<h3>File:" not in org:
            return ""
        
        start = org.find(":")
        end = org.find("</h3>")
        
        if start < 0 or end < 0:
            return ""
        
        return org[start + 1:end].strip()
    
    def _build_spec(self) -> None:
        """스펙 빌드"""
        self.dic_spec = {
            MatrixItem.V_G: MatrixSpec(MatrixItem.V_G, [11, 21, 31]),
            MatrixItem.LEVEL: MatrixSpec(MatrixItem.LEVEL, [6, 11]),
            MatrixItem.CALLING: MatrixSpec(MatrixItem.CALLING, [6, 11]),
            MatrixItem.CALLS: MatrixSpec(MatrixItem.CALLS, [8, 13]),
        }
        
        self.dic_spec_over_count = {
            MatrixItem.V_G: MatrixSpec(MatrixItem.V_G, [0, 0, 0, 0]),
            MatrixItem.LEVEL: MatrixSpec(MatrixItem.LEVEL, [0, 0, 0]),
            MatrixItem.CALLING: MatrixSpec(MatrixItem.CALLING, [0, 0, 0]),
            MatrixItem.CALLS: MatrixSpec(MatrixItem.CALLS, [0, 0, 0]),
        }
    
    def clear(self) -> None:
        """초기화"""
        self.list_result.clear()
        
        for spec in self.dic_spec_over_count.values():
            spec.clear(True)


def parse_qac_report(filepath: Path, old_version: bool = False) -> QACDataManager:
    """QAC 리포트 파싱 메인 함수"""
    manager = QACDataManager()
    if manager.read_file(old_version, filepath):
        return manager
    else:
        raise ValueError("Failed to parse QAC report")
