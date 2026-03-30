"""VectorCAST HTML 리포트 파서

TResultParser C# 프로그램의 로직을 Python으로 포팅한 VectorCAST 리포트 파서입니다.
TestCaseData, Metrics, AggregateCoverage, ExecutionResult 리포트를 파싱합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


class VCASTVersion(Enum):
    """VectorCAST 버전"""
    Ver2021 = 0
    Ver2024 = 1
    Ver2025 = 2


class ReportType(Enum):
    """리포트 타입"""
    TestCaseData = "TestCaseData"
    Metrics = "Metrics"
    AggregateCoverage = "AggregateCoverage"
    ExecutionResult = "ExecutionResult"


class MatricsType(Enum):
    """메트릭 타입"""
    Statement = 0  # Unit Test
    Functions = 1  # Integration Test
    NONE = 2  # None (예약어이므로 NONE으로 변경)


@dataclass
class CoverageItem:
    """커버리지 아이템"""
    count: int = 0
    total: int = 0
    coverage_str: str = ""
    
    def __init__(self, data: str = ""):
        self.count = 0
        self.total = 0
        self.coverage_str = data
        if data:
            # "5 / 5 (100%)" 또는 "5/5(100%)" 형식 파싱
            parts = re.split(r'[/\(]', data.replace(" ", ""))
            if len(parts) >= 2:
                try:
                    self.count = int(parts[0])
                    self.total = int(parts[1])
                except ValueError:
                    pass
    
    @property
    def passed(self) -> bool:
        """모든 항목이 커버되었는지"""
        return self.total > 0 and self.count == self.total
    
    @property
    def percentage(self) -> str:
        """퍼센트 문자열"""
        if self.total == 0:
            return "-"
        pct = int(self.count * 100 / self.total)
        return f"{pct} %"
    
    @property
    def coverage(self) -> str:
        """커버리지 문자열"""
        if self.coverage_str:
            return self.coverage_str
        if self.total == 0:
            return "0 / 0 (0 %)"
        pct = int(self.count * 100 / self.total)
        return f"{self.count} / {self.total} ({pct} %)"


@dataclass
class MatricStatementItem:
    """Statement 메트릭 아이템"""
    id: str = ""
    unit_name: str = ""
    subprogram: str = ""
    complexity: int = 0
    statements: Optional[CoverageItem] = None
    branches: Optional[CoverageItem] = None
    is_function: bool = False
    functions_call: Optional[CoverageItem] = None
    unit_id: str = ""
    
    @property
    def is_valid(self) -> bool:
        return bool(self.unit_name and self.subprogram)


@dataclass
class MatricFunCallItem:
    """Function Call 메트릭 아이템"""
    file_id: str = ""
    unit_name: str = ""
    subprogram: str = ""
    complexity: int = 0
    functions: Optional[CoverageItem] = None
    functions_call: Optional[CoverageItem] = None
    unit_id: str = ""
    
    @property
    def id(self) -> str:
        if not self.unit_name:
            return self.file_id
        return f"{self.file_id}:{self.unit_name}"
    
    @property
    def is_valid(self) -> bool:
        return bool(self.unit_name and self.subprogram)


@dataclass
class MatixDataBank:
    """메트릭 데이터 뱅크"""
    mtype: MatricsType
    unit_name: str
    dic_data: Dict[str, Any] = field(default_factory=dict)
    
    def add(self, item: Any) -> bool:
        """아이템 추가"""
        if hasattr(item, 'subprogram'):
            if item.subprogram not in self.dic_data:
                self.dic_data[item.subprogram] = item
                return True
        return False
    
    def exists_subprogram(self, subprogram: str) -> bool:
        """서브프로그램 존재 여부"""
        return subprogram in self.dic_data


@dataclass
class SubFunctionExecution:
    """서브함수 실행 정보"""
    order: str
    name: str
    executed: bool


@dataclass
class MetricsBank:
    """Metrics 리포트 뱅크"""
    environment: str = ""
    statement_data: Dict[str, MatixDataBank] = field(default_factory=dict)  # Unit Test
    functions_data: Dict[str, MatixDataBank] = field(default_factory=dict)  # Integration Test
    sub_functions: Dict[str, List[SubFunctionExecution]] = field(default_factory=dict)  # AggregateCoverage


@dataclass
class VCastHeader:
    """테스트 케이스 헤더 정보"""
    component_name: str
    unit_name: str
    test_case_name: str
    test_case_index: str
    filename: str


@dataclass
class TestCaseItem:
    """테스트 케이스 데이터"""
    header: VCastHeader
    input_data: Dict[str, str] = field(default_factory=dict)
    expected_result: Dict[str, str] = field(default_factory=dict)
    user_code: Dict[str, str] = field(default_factory=dict)
    description: str = ""


@dataclass
class TestResultItem:
    """실행 결과 데이터"""
    header: VCastHeader
    passed: bool = False
    actual_result: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # (actual, expected)
    user_code: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TCBank:
    """테스트 케이스 뱅크"""
    environment: str = ""
    component_name: str = ""
    unit_mode: bool = False
    test_cases: Dict[str, List[TestCaseItem]] = field(default_factory=dict)
    test_results: Dict[str, List[TestResultItem]] = field(default_factory=dict)
    input_names: List[str] = field(default_factory=list)
    exp_result_names: List[str] = field(default_factory=list)
    act_result_names: List[str] = field(default_factory=list)
    max_input_count: int = 0
    max_exp_result_count: int = 0
    max_act_result_count: int = 0

    @property
    def test_count(self) -> int:
        """전체 테스트 케이스 수"""
        return len(self.test_cases) if self.test_cases else len(self.test_results)

    @property
    def passed_count(self) -> int:
        """통과한 테스트 케이스 수"""
        if not self.test_results:
            return 0
        return sum(1 for items in self.test_results.values() 
                   if any(item.passed for item in items))


class VIMLib:
    """VectorCAST HTML 파싱 유틸리티"""
    
    EMPTY_DATA = "&nbsp;"

    @staticmethod
    def check_string_exists(text: str, pattern: str) -> bool:
        """문자열에 패턴이 존재하는지 확인"""
        if not text or not pattern:
            return False
        return pattern in text

    @staticmethod
    def get_table_contents(line: str, tag: str) -> Optional[List[str]]:
        """테이블 셀 내용 추출"""
        if not line or tag not in line:
            return None
        if BeautifulSoup:
            try:
                soup = BeautifulSoup(line, "html.parser")
                items = [t.get_text(strip=True) for t in soup.find_all(tag)]
                if items:
                    return items
            except Exception:
                pass
        # <td> 또는 <th> 태그 사이의 내용 추출
        pattern = f"<{tag}[^>]*>(.*?)</{tag}>"
        matches = re.findall(pattern, line, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]

    @staticmethod
    def get_table_row_data_only(line: str) -> Optional[List[str]]:
        """테이블 행의 데이터만 추출 (태그 제외)"""
        if not line:
            return None
        if BeautifulSoup:
            try:
                soup = BeautifulSoup(line, "html.parser")
                cells = [t.get_text(strip=True) for t in soup.find_all(["td", "th"])]
                if cells:
                    return [c.replace(VIMLib.EMPTY_DATA, "") for c in cells if c.strip()]
            except Exception:
                pass
        # <tr>, <th>, <td> 태그 사이의 텍스트 추출
        pattern = r"<t[dh][^>]*>(.*?)</t[dh]>"
        matches = re.findall(pattern, line, re.DOTALL)
        return [m.strip().replace(VIMLib.EMPTY_DATA, "") for m in matches if m.strip()]

    @staticmethod
    def get_one_td_value(line: str) -> str:
        """단일 td 셀의 값 추출"""
        if not line or "td" not in line:
            return ""
        
        pattern = r"<td[^>]*>(.*?)</td>"
        matches = re.findall(pattern, line, re.DOTALL)
        if matches:
            value = matches[0].strip()
            return value.replace(VIMLib.EMPTY_DATA, "")
        return ""

    @staticmethod
    def environment_name(line: str) -> str:
        """환경명 추출"""
        if not line:
            return ""
        
        pattern = r"<td[^>]*>(.*?)</td>"
        matches = re.findall(pattern, line)
        if matches:
            return matches[0].strip()
        return ""

    @staticmethod
    def substring(text: str, delimiter: str, before: bool) -> str:
        """구분자 기준으로 문자열 분리"""
        if not text or not delimiter:
            return ""
        
        idx = text.find(delimiter)
        if idx < 0:
            return ""
        
        if before:
            return text[:idx]
        else:
            return text[idx + len(delimiter):]


class VectorCASTParser:
    """VectorCAST HTML 리포트 파서"""
    
    # VectorCAST 버전별 Contents Block 라인 번호
    LINENO_CONTENTS_BLOCK = {
        VCASTVersion.Ver2021: 193,
        VCASTVersion.Ver2024: 218,
        VCASTVersion.Ver2025: 401,
    }
    
    TCDATA_ITEM_ROWCOUNT = 5

    def __init__(self, version: VCASTVersion = VCASTVersion.Ver2025):
        self.version = version
        self.lines: List[str] = []

    def parse_testcase_data(self, filepath: Path) -> TCBank:
        """TestCaseData 리포트 파싱"""
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        # 파일을 라인별로 읽기
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()
        
        tcbank = TCBank()
        tcbank.unit_mode = False  # 기본값
        
        # 파일 타입 확인
        if len(self.lines) < 5:
            raise ValueError("Invalid file format")
        
        title_line = self.lines[4] if len(self.lines) > 4 else ""
        if "Test Case Data Report" not in title_line:
            raise ValueError("Not a Test Case Data Report")
        
        # Contents Block 찾기
        contents_line_no = self.LINENO_CONTENTS_BLOCK.get(self.version, 401)
        if contents_line_no >= len(self.lines):
            # 라인 번호가 맞지 않으면 검색
            for i, line in enumerate(self.lines):
                if "contents-block" in line:
                    contents_line_no = i
                    break
        
        # Environment Name 찾기
        for i in range(contents_line_no, min(contents_line_no + 50, len(self.lines))):
            line = self.lines[i]
            if "<th>Environment Name</th>" in line:
                tcbank.environment = VIMLib.environment_name(self.lines[i + 1] if i + 1 < len(self.lines) else "")
                break
        
        # Test Case 섹션 파싱
        test_name = ""
        for i, line in enumerate(self.lines):
            # Test Case Header 찾기
            if "<!-- TestcaseSectionsHeader -->" in line:
                header = self._read_tc_header(filepath.stem, i, True)
                if not header:
                    continue
                
                if not tcbank.component_name:
                    tcbank.component_name = header.component_name
                
                # Test Case Data 찾기
                tc_item = None
                for j in range(i, min(i + 200, len(self.lines))):
                    if "<!-- TestCaseData -->" in self.lines[j]:
                        tc_item = self._read_tc_data(j, header)
                        break
                
                if tc_item:
                    if test_name != tc_item.header.test_case_name:
                        test_name = tc_item.header.test_case_name
                        tcbank.test_cases[test_name] = []
                    tcbank.test_cases[test_name].append(tc_item)
                    
                    # 필드명 업데이트
                    for key in tc_item.input_data.keys():
                        if key not in tcbank.input_names:
                            tcbank.input_names.append(key)
                    for key in tc_item.expected_result.keys():
                        if key not in tcbank.exp_result_names:
                            tcbank.exp_result_names.append(key)
                    
                    tcbank.max_input_count = max(tcbank.max_input_count, len(tc_item.input_data))
                    tcbank.max_exp_result_count = max(tcbank.max_exp_result_count, len(tc_item.expected_result))
        
        return tcbank

    def parse_execution_result(self, filepath: Path) -> TCBank:
        """ExecutionResult 리포트 파싱"""
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()
        
        tcbank = TCBank()
        
        # 파일 타입 확인
        if len(self.lines) < 5:
            raise ValueError("Invalid file format")
        
        title_line = self.lines[4] if len(self.lines) > 4 else ""
        if "Execution Results Report" not in title_line:
            raise ValueError("Not an Execution Results Report")
        
        # Execution Result 섹션 파싱
        test_name = ""
        total_passed = True
        
        for i, line in enumerate(self.lines):
            if "<!-- ExecutionResults/testcase_header -->" in line:
                header = self._read_tc_header(filepath.stem, i, False)
                if not header:
                    continue
                
                # Execution Result 찾기
                tr_item = None
                for j in range(i, min(i + 300, len(self.lines))):
                    if "<!-- ExecutionResults/testcase_header -->" in self.lines[j]:
                        tr_item = self._read_exe_result(j, header)
                        break
                
                if tr_item:
                    if not tr_item.passed:
                        total_passed = False
                    
                    if test_name != tr_item.header.test_case_name:
                        test_name = tr_item.header.test_case_name
                        tcbank.test_results[test_name] = []
                        total_passed = True
                    
                    tcbank.test_results[test_name].append(tr_item)
                    
                    # 필드명 업데이트
                    for key in tr_item.actual_result.keys():
                        if key not in tcbank.act_result_names:
                            tcbank.act_result_names.append(key)
                    
                    tcbank.max_act_result_count = max(tcbank.max_act_result_count, len(tr_item.actual_result))
        
        return tcbank

    def _read_tc_header(self, filename: str, start_idx: int, is_testcase: bool) -> Optional[VCastHeader]:
        """테스트 케이스 헤더 읽기"""
        idx = start_idx
        header_offset = 9 if self.version == VCASTVersion.Ver2021 else (10 if self.version == VCASTVersion.Ver2024 else 11)
        if not is_testcase:
            header_offset += 1
        
        idx += header_offset
        
        if idx >= len(self.lines):
            return None
        
        unit_name = ""
        comp_name = ""
        tc_name = ""
        
        # Unit Under Test 찾기
        for i in range(idx, min(idx + 10, len(self.lines))):
            line = self.lines[i]
            if "<th>Unit Under Test</th>" in line:
                data = VIMLib.get_table_row_data_only(line)
                if data and len(data) >= 2:
                    comp_name = data[1]
                    if is_testcase and len(data) >= 4:
                        unit_name = data[3]
                break
        
        if not is_testcase:
            # Subprogram 찾기
            for i in range(idx, min(idx + 10, len(self.lines))):
                line = self.lines[i]
                if "<th>Subprogram</th>" in line:
                    data = VIMLib.get_table_row_data_only(line)
                    if data and len(data) >= 2:
                        unit_name = data[1]
                    break
        
        # Test Case Name 찾기
        for i in range(idx, min(idx + 10, len(self.lines))):
            line = self.lines[i]
            if "<th>Test Case Name</th>" in line:
                data = VIMLib.get_table_row_data_only(line)
                if data and len(data) >= 2:
                    tc_name = data[1]
                break
        
        if not comp_name or not tc_name:
            return None
        
        # TC Index 추출 (TC 이름에서)
        tc_index = tc_name.split('.')[-1] if '.' in tc_name else tc_name
        
        return VCastHeader(
            component_name=comp_name,
            unit_name=unit_name,
            test_case_name=tc_name,
            test_case_index=tc_index,
            filename=filename
        )

    def _read_tc_data(self, start_idx: int, header: VCastHeader) -> Optional[TestCaseItem]:
        """테스트 케이스 데이터 읽기"""
        idx = start_idx + 10
        if idx >= len(self.lines):
            return None
        
        tc_item = TestCaseItem(header=header)
        
        # Requirements/Notes 찾기
        for i in range(idx, min(idx + 50, len(self.lines))):
            line = self.lines[i]
            if "<h4>Requirements/Notes</h4>" in line:
                # Note 읽기
                note_text = ""
                for j in range(i + 1, min(i + 20, len(self.lines))):
                    note_line = self.lines[j]
                    note_text += note_line
                    if "</pre>" in note_line:
                        note_text = note_text.replace("</pre>", "").replace("<pre>", "")
                        note_text = note_text.replace("&lt;", "<").replace("&gt;", ">")
                        tc_item.description = note_text.strip()
                        idx = j + 3
                        break
                break
        
        # Input Test Data 찾기
        for i in range(idx, min(idx + 50, len(self.lines))):
            line = self.lines[i]
            if "<h4>Input Test Data</h4>" in line:
                if "This test has no" in self.lines[i + 1]:
                    idx = i + 3
                else:
                    idx = i + 4
                    idx = self._read_testcase_item(idx, True, tc_item)
                    if idx < 0:
                        return None
                    idx += self.TCDATA_ITEM_ROWCOUNT
                break
        
        # Expected Test Data 찾기
        for i in range(idx, min(idx + 50, len(self.lines))):
            line = self.lines[i]
            if "<h4>Expected Test Data</h4>" in line:
                if "This test has no" in self.lines[i + 1]:
                    idx = i + 4
                else:
                    idx = i + 4
                    idx = self._read_testcase_item(idx, False, tc_item)
                    if idx < 0:
                        return None
                break
        
        return tc_item

    def _read_testcase_item(self, start_idx: int, is_input: bool, tc_item: TestCaseItem) -> int:
        """테스트 케이스 아이템 읽기 (Input 또는 Expected)"""
        idx = start_idx
        dicnames: Dict[int, str] = {}
        dicsubprogram: Dict[int, str] = {}
        datatype = None  # UUT, UUT_Globals, UUT_Subprograms, StubbedSubprograms
        
        for i in range(idx, len(self.lines)):
            line = self.lines[i]
            
            if "class=" in line:
                # Class level 추출
                match = re.search(r"class=['\"]i(\d+)", line)
                if match:
                    classlevel = int(match.group(1))
                    
                    if classlevel == 0:
                        dicnames.clear()
                        dicsubprogram.clear()
                        if "Stubbed Subprograms" in line:
                            datatype = "StubbedSubprograms"
                        elif "UUT" in line:
                            datatype = "UUT"
                    
                    elif classlevel == 1:
                        if "Globals" in line:
                            datatype = "UUT_Globals"
                        elif "Subprogram" in line:
                            datatype = "UUT_Subprograms"
                            td_value = VIMLib.get_one_td_value(line)
                            variable = VIMLib.substring(td_value, ":", False).strip()
                            if variable == tc_item.header.unit_name:
                                datatype = "UUT_Globals"
                                variable = ""
                            else:
                                dicsubprogram[classlevel] = variable
                    
                    elif classlevel >= 2:
                        variable_temp = VIMLib.get_one_td_value(line)
                        
                        if datatype == "UUT_Subprograms":
                            # Function parameter 처리
                            variable = self._get_function_params(dicsubprogram, classlevel, variable_temp)
                            if i + 2 < len(self.lines):
                                valuedata = VIMLib.get_one_td_value(self.lines[i + 2])
                                valuedata = self._clean_value(valuedata)
                                
                                if valuedata:
                                    if is_input:
                                        tc_item.input_data[variable] = valuedata
                                    else:
                                        tc_item.expected_result[variable] = valuedata
                        
                        elif datatype == "UUT_Globals":
                            if classlevel == 2:
                                variable = ""
                                dicnames.clear()
                            
                            variable = self._get_variable_names(dicnames, classlevel, variable_temp)
                            if i + 2 < len(self.lines):
                                valuedata = VIMLib.get_one_td_value(self.lines[i + 2])
                                valuedata = self._clean_value(valuedata)
                                
                                if valuedata:
                                    if is_input:
                                        tc_item.input_data[variable] = valuedata
                                    else:
                                        tc_item.expected_result[variable] = valuedata
                        
                        elif datatype == "StubbedSubprograms":
                            if classlevel == 2:
                                variable_temp = VIMLib.substring(variable_temp, ":", False).strip()
                            variable = self._get_function_params(dicnames, classlevel, variable_temp)
                            if i + 2 < len(self.lines):
                                valuedata = VIMLib.get_one_td_value(self.lines[i + 2])
                                if valuedata:
                                    if is_input:
                                        tc_item.input_data[variable] = valuedata
                                    else:
                                        tc_item.expected_result[variable] = valuedata
            
            i += self.TCDATA_ITEM_ROWCOUNT
            
            if i + 1 < len(self.lines) and "</table>" in self.lines[i + 1]:
                idx = i
                break
        
        if not is_input:
            # User Code 찾기
            for i in range(idx, len(self.lines)):
                line = self.lines[i]
                if "<h4>Test Case / Parameter Expected User Code</h4>" in line:
                    self._parse_user_code_of_testcase(line, tc_item)
                    break
                if i + 1 < len(self.lines) and "<!-- TestcaseSectionsFooter -->" in self.lines[i + 1]:
                    break
        
        return idx

    def _read_exe_result(self, start_idx: int, header: VCastHeader) -> Optional[TestResultItem]:
        """실행 결과 읽기"""
        idx = start_idx + 3
        if idx >= len(self.lines):
            return None
        
        tr_item = TestResultItem(header=header, passed=False)
        
        # Execution Results 찾기
        for i in range(idx, min(idx + 20, len(self.lines))):
            line = self.lines[i]
            if "</a>Execution Results" in line:
                if "(PASS)" in line:
                    tr_item.passed = True
                idx = i + 9
                break
        
        # Result Table 찾기
        for i in range(idx, min(idx + 100, len(self.lines))):
            line = self.lines[i]
            if "table table-small table-hover" in line:
                idx = i + 11
                idx = self._read_exe_result_item(idx, tr_item)
                break
            if "<!-- ExecutionResult/testcase_footer -->" in line:
                break
        
        return tr_item

    def _read_exe_result_item(self, start_idx: int, tr_item: TestResultItem) -> int:
        """실행 결과 아이템 읽기"""
        idx = start_idx
        dicnames: Dict[int, str] = {}
        usercode = False
        
        for i in range(idx, len(self.lines)):
            line = self.lines[i]
            
            if "<tr" in line:
                if "User Code Expected Values" in line:
                    usercode = True
                    i += 3
                    line = self.lines[i] if i < len(self.lines) else ""
                
                if "class=" in line:
                    if usercode:
                        # User code 결과 파싱
                        user_result = self._parse_user_code_of_actual_result(line)
                        if user_result:
                            tr_item.user_code.append(user_result)
                    else:
                        # 일반 결과 파싱
                        match = re.search(r"class=['\"]i(\d+)", line)
                        if match:
                            classlevel = int(match.group(1))
                            variable_temp = self._replace_brace(VIMLib.get_one_td_value(line))
                            
                            if ":" in variable_temp:
                                dicnames.clear()
                            else:
                                variable = self._get_variable_names(dicnames, classlevel, variable_temp)
                                if i + 2 < len(self.lines):
                                    actual_value = self._replace_brace(VIMLib.get_one_td_value(self.lines[i + 2]))
                                    if i + 3 < len(self.lines):
                                        marker_line = self.lines[i + 3]
                                        if "success-marker" in marker_line:
                                            tr_item.actual_result[variable] = (actual_value, actual_value)
                                        elif "fail-marker" in marker_line:
                                            expected_value = self._remove_brackets(VIMLib.get_one_td_value(marker_line))
                                            tr_item.actual_result[variable] = (actual_value, expected_value.strip())
            
            # 다음 행 찾기
            for j in range(i, min(i + 5, len(self.lines))):
                if "</tr>" in self.lines[j]:
                    i = j
                    break
            
            if "<!-- ExecutionResult/testcase_footer -->" in line:
                idx = i
                break
        
        return idx

    def _get_function_params(self, dicnames: Dict[int, str], level: int, variable_temp: str) -> str:
        """함수 파라미터 이름 생성"""
        if level < 1:
            return ""
        
        dicnames[level] = variable_temp
        
        if level == 1:
            return variable_temp
        
        variable = ""
        for key in sorted(dicnames.keys()):
            if key > level:
                break
            data = dicnames[key]
            if variable and "[" not in data:
                variable += "() "
            variable += data
        
        return variable

    def _get_variable_names(self, dicnames: Dict[int, str], level: int, variable_temp: str) -> str:
        """변수 이름 생성"""
        var_name = self._remove_brace(variable_temp)
        dicnames[level] = var_name
        
        variable = ""
        for key in sorted(dicnames.keys()):
            if key > level:
                break
            data = dicnames[key]
            if variable and "[" not in data:
                variable += "."
            variable += data
        
        return variable

    def _clean_value(self, value: str) -> str:
        """값 정리"""
        if not value:
            return ""
        
        if "&lt;&lt;" in value:
            if "malloc " in value:
                return ""
            else:
                return self._remove_brace(value)
        
        return value

    def _replace_brace(self, text: str) -> str:
        """&lt; &gt;를 < >로 변환"""
        if not text:
            return ""
        return text.replace("&lt;", "<").replace("&gt;", ">")

    def _remove_brace(self, text: str) -> str:
        """&lt; &gt; 제거"""
        if not text:
            return ""
        return text.replace("&lt;", "").replace("&gt;", "")

    def _remove_brackets(self, text: str) -> str:
        """대괄호 제거"""
        if not text:
            return ""
        return text.replace("[", "").replace("]", "")

    def _parse_user_code_of_testcase(self, line: str, tc_item: TestCaseItem) -> bool:
        """테스트 케이스의 User Code 파싱"""
        if not line:
            return False
        
        if "This test has no expected user code" in line:
            return True
        
        line_temp = self._replace_brace(line)
        pattern = r"<p>(.*?)</p>"
        matches = re.findall(pattern, line_temp)
        
        if matches and len(matches) % 2 == 0:
            for i in range(0, len(matches), 2):
                name = matches[i].strip()
                if "GLOBAL" in name:
                    idx = name.rfind(".")
                    if idx >= 0:
                        name = name[idx + 1:]
                
                message = matches[i + 1].strip().replace("{", " ").replace("}", " ")
                tc_item.user_code[name.strip()] = message.strip()
        
        return True

    def _parse_user_code_of_actual_result(self, line: str) -> Optional[Dict[str, Any]]:
        """실제 결과의 User Code 파싱"""
        if not line:
            return None
        
        line_temp = self._replace_brace(line)
        pattern = r"<td[^>]*>(.*?)</td>"
        matches = re.findall(pattern, line_temp)
        
        if len(matches) == 2:
            first_string = matches[0].strip()
            idx = first_string.find("==")
            if idx < 0:
                return None
            
            name = first_string[:idx]
            if "GLOBAL" in name:
                idx = name.rfind(".")
                if idx >= 0:
                    name = name[idx + 1:-4]  # ">>" 제거
            
            match = False
            if "[fail]" in line_temp:
                first_string += ", NG"
            elif "<match>" in line_temp:
                match = True
                first_string += ", OK"
            else:
                return None
            
            return {
                "name": name,
                "match": match,
                "message": first_string
            }
        
        return None


    def parse_metrics(self, filepath: Path) -> MetricsBank:
        """Metrics 리포트 파싱"""
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()
        
        metrics_bank = MetricsBank()
        
        # 파일 타입 확인
        if len(self.lines) < 2:
            raise ValueError("Invalid file format")
        
        if "VectorCAST Report header" not in self.lines[1]:
            raise ValueError("Not a VectorCAST Report")
        
        # Environment Name 찾기
        env_line_no = {
            VCASTVersion.Ver2021: 207,
            VCASTVersion.Ver2024: 232,
            VCASTVersion.Ver2025: 418,
        }.get(self.version, 418)
        
        if env_line_no < len(self.lines):
            for i in range(env_line_no, min(env_line_no + 10, len(self.lines))):
                line = self.lines[i]
                if "<tr><th>Environment Name</th>" in line:
                    metrics_bank.environment = VIMLib.environment_name(self.lines[i + 1] if i + 1 < len(self.lines) else "")
                    break
        
        # Coverage Type 찾기
        coverage_line_no = {
            VCASTVersion.Ver2021: 220,
            VCASTVersion.Ver2024: 245,
            VCASTVersion.Ver2025: 429,
        }.get(self.version, 429)
        
        mtype = MatricsType.NONE
        if coverage_line_no < len(self.lines):
            line = self.lines[coverage_line_no]
            if "<h3 id=\"coverage_type\">" in line:
                coverage_text = VIMLib.get_one_td_value(line)
                if "Statement" in coverage_text or "Statement+Branch" in coverage_text:
                    mtype = MatricsType.Statement
                elif "Function" in coverage_text or "Function+Function Call" in coverage_text:
                    mtype = MatricsType.Functions
        
        if mtype == MatricsType.NONE:
            raise ValueError("Invalid Metrics Report type")
        
        # 테이블 헤더 찾기
        header_line_no = coverage_line_no + 4
        if header_line_no >= len(self.lines):
            raise ValueError("Invalid Metrics Report format")
        
        # 데이터 행 파싱 - 테이블의 tbody 내부 행들
        data_start = header_line_no + 5
        unit_pre = ""
        i = data_start
        
        while i < len(self.lines):
            line = self.lines[i]
            
            # tbody 종료 또는 TOTALS 행이면 종료
            if "</tbody>" in line or "TOTALS" in line.upper() or "GRAND TOTALS" in line.upper():
                break
            
            # tr 태그 시작 찾기
            if "<tr>" in line:
                # tr 태그 내의 모든 td 추출
                tr_lines = []
                j = i
                while j < len(self.lines):
                    tr_lines.append(self.lines[j])
                    if "</tr>" in self.lines[j]:
                        break
                    j += 1
                
                tr_content = "".join(tr_lines)
                coldata = VIMLib.get_table_contents(tr_content, "td")
                
                if coldata and len(coldata) >= 4:
                    unit_name = coldata[0].strip()
                    if not unit_name or unit_name == VIMLib.EMPTY_DATA:
                        if not unit_pre:
                            i = j + 1
                            continue
                        unit_name = unit_pre
                    else:
                        unit_pre = unit_name
                    
                    # TOTALS 행 건너뛰기
                    if "TOTALS" in unit_name.upper():
                        i = j + 1
                        continue
                    
                    # 데이터 뱅크 가져오기 또는 생성
                    if mtype == MatricsType.Statement:
                        if unit_name not in metrics_bank.statement_data:
                            metrics_bank.statement_data[unit_name] = MatixDataBank(mtype, unit_name)
                        bank = metrics_bank.statement_data[unit_name]
                    else:
                        if unit_name not in metrics_bank.functions_data:
                            metrics_bank.functions_data[unit_name] = MatixDataBank(mtype, unit_name)
                        bank = metrics_bank.functions_data[unit_name]
                    
                    # 아이템 생성
                    if mtype == MatricsType.Statement:
                        subprogram = coldata[1].strip() if len(coldata) > 1 else ""
                        complexity_str = coldata[2].strip() if len(coldata) > 2 else "0"
                        try:
                            complexity = int(complexity_str)
                        except ValueError:
                            complexity = 0
                        
                        item = MatricStatementItem(
                            id=metrics_bank.environment,
                            unit_name=unit_name,
                            subprogram=subprogram,
                            complexity=complexity,
                        )
                        
                        if len(coldata) > 3:
                            stmt_text = coldata[3].strip()
                            item.statements = CoverageItem(stmt_text)
                        
                        if len(coldata) > 4:
                            branch_text = coldata[4].strip()
                            item.branches = CoverageItem(branch_text)
                        
                        if item.is_valid:
                            bank.add(item)
                    
                    elif mtype == MatricsType.Functions:
                        subprogram = coldata[1].strip() if len(coldata) > 1 else ""
                        complexity_str = coldata[2].strip() if len(coldata) > 2 else "0"
                        try:
                            complexity = int(complexity_str)
                        except ValueError:
                            complexity = 0
                        
                        item = MatricFunCallItem(
                            file_id=metrics_bank.environment,
                            unit_name=unit_name,
                            subprogram=subprogram,
                            complexity=complexity,
                        )
                        
                        if len(coldata) > 3:
                            func_text = coldata[3].strip()
                            item.functions = CoverageItem(func_text)
                        
                        if len(coldata) > 4:
                            fcall_text = coldata[4].strip()
                            item.functions_call = CoverageItem(fcall_text)
                        
                        if item.is_valid:
                            bank.add(item)
                
                i = j + 1
            else:
                i += 1
        
        return metrics_bank

    def parse_aggregate_coverage(self, filepath: Path) -> MetricsBank:
        """AggregateCoverage 리포트 파싱"""
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()
        
        metrics_bank = MetricsBank()
        
        # 파일 타입 확인
        if len(self.lines) < 2:
            raise ValueError("Invalid file format")
        
        if "VectorCAST Report header" not in self.lines[1]:
            raise ValueError("Not a VectorCAST Report")
        
        # Aggregate Coverage Report 확인
        agg_title_line = {
            VCASTVersion.Ver2021: 210,
            VCASTVersion.Ver2024: 210,
            VCASTVersion.Ver2025: 410,
        }.get(self.version, 410)
        
        is_agg_coverage = False
        for i in range(agg_title_line, min(agg_title_line + 30, len(self.lines))):
            if "Aggregate Coverage Report" in self.lines[i]:
                is_agg_coverage = True
                break
        
        if not is_agg_coverage:
            raise ValueError("Not an Aggregate Coverage Report")
        
        # Environment Name 찾기
        for i, line in enumerate(self.lines):
            if "<th>Environment Name</th>" in line and i + 1 < len(self.lines):
                metrics_bank.environment = VIMLib.environment_name(self.lines[i + 1])
                break
        
        # Aggregate Coverage 데이터 파싱
        agg_coverage_line = {
            VCASTVersion.Ver2021: 250,
            VCASTVersion.Ver2024: 250,
            VCASTVersion.Ver2025: 438,
        }.get(self.version, 438)
        
        module_name = ""
        item_count = 0
        
        for i in range(agg_coverage_line, len(self.lines)):
            line = self.lines[i]
            
            if "<span class=" in line and "-marker\">" in line:
                success = "success-marker" in line
                coldata = VIMLib.get_table_contents(line, "span")
                
                if not coldata or (len(coldata) != 1 and len(coldata) != 4):
                    continue
                
                data = coldata[0] if len(coldata) == 1 else coldata[3]
                bpos = data.find("(")
                if bpos < 0:
                    continue
                
                data = data[:bpos]
                
                # 공백으로 분리
                listdata = [s for s in data.split() if s]
                if len(listdata) < 3:
                    continue
                
                module_order = listdata[0]
                suborder = listdata[1]
                subfunction = listdata[-1]
                
                if not module_order or not suborder or not subfunction:
                    continue
                
                if suborder == "0":
                    module_name = subfunction
                    if module_name not in metrics_bank.sub_functions:
                        metrics_bank.sub_functions[module_name] = []
                    item_count += 1
                else:
                    if module_name and module_name in metrics_bank.sub_functions:
                        # 기존 항목 찾기
                        existing = None
                        for item in metrics_bank.sub_functions[module_name]:
                            if item.order == suborder:
                                existing = item
                                break
                        
                        if existing:
                            if not existing.executed and success:
                                existing.executed = success
                        else:
                            metrics_bank.sub_functions[module_name].append(
                                SubFunctionExecution(suborder, subfunction, success)
                            )
        
        if item_count == 0:
            raise ValueError("No aggregate coverage data found")
        
        return metrics_bank


def parse_vcast_report(filepath: Path, report_type: ReportType, version: VCASTVersion = VCASTVersion.Ver2025) -> Any:
    """VectorCAST 리포트 파싱 메인 함수"""
    parser = VectorCASTParser(version=version)
    
    if report_type == ReportType.TestCaseData:
        return parser.parse_testcase_data(filepath)
    elif report_type == ReportType.ExecutionResult:
        return parser.parse_execution_result(filepath)
    elif report_type == ReportType.Metrics:
        return parser.parse_metrics(filepath)
    elif report_type == ReportType.AggregateCoverage:
        return parser.parse_aggregate_coverage(filepath)
    else:
        raise ValueError(f"Unsupported report type: {report_type}")
