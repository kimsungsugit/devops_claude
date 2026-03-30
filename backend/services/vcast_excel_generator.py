"""VectorCAST Excel 리포트 생성기

TResultParser C# 프로그램의 Excel 생성 로직을 Python으로 포팅한 생성기입니다.
openpyxl을 사용하여 TResultParser와 동일한 형식의 Excel 리포트를 생성합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.comments import Comment
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None
    Font = None
    PatternFill = None
    Alignment = None
    Border = None
    Side = None
    Comment = None
    get_column_letter = None

from backend.services.vcast_parser import (
    TCBank, TestCaseItem, TestResultItem,
    MetricsBank, MatricsType, MatricStatementItem, MatricFunCallItem,
    CoverageItem, MatixDataBank
)


class XlsCellStyle(Enum):
    """Excel 셀 스타일"""
    Title = 0
    Caption = 1
    General = 2
    Fixed = 3
    BgSkyBlue = 4
    BgYellow = 5
    BgOrange = 6
    BgRed = 7
    BgPink = 8
    BgSkyBlueL = 9
    BgPurpleL = 10
    BgPeachL = 11
    BgLightBlue = 12
    BgLightGray = 13
    BgPinkFRed = 14
    BgBlueFRed = 15
    FgRed = 16
    NONE = 17  # 예약어 None 대신 NONE 사용


class BorderEdge(Enum):
    """테두리 위치"""
    Left = 0
    Right = 1
    Top = 2
    Bottom = 3


@dataclass
class ExcelStyle:
    """Excel 스타일 정보"""
    font_color: str = "000000"
    font_bold: bool = False
    bg_color: Optional[str] = None
    border: bool = True


class XlsxManager:
    """Excel 파일 관리 클래스 (TResultParser의 XlsxManager 포팅)"""
    
    FONTSIZE_DEFAULT = 10
    XLS_TITLE_COLCOUNT = 14
    
    def __init__(self):
        self.workbook: Optional[Workbook] = None
        self.worksheet = None
        self.filepath: Optional[Path] = None
        self._styles = self._init_styles()
    
    def _init_styles(self) -> Dict[XlsCellStyle, ExcelStyle]:
        """스타일 초기화"""
        return {
            XlsCellStyle.Title: ExcelStyle(
                font_color="FFFFFF",
                font_bold=True,
                bg_color="203764"
            ),
            XlsCellStyle.Caption: ExcelStyle(
                font_color="000000",
                font_bold=True,
                bg_color="DDEBF7"
            ),
            XlsCellStyle.General: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color=None
            ),
            XlsCellStyle.Fixed: ExcelStyle(
                font_color="000000",
                font_bold=True,
                bg_color="EEEEEE"
            ),
            XlsCellStyle.BgYellow: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="FFFF00"
            ),
            XlsCellStyle.BgOrange: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="FFA500"
            ),
            XlsCellStyle.BgRed: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="FF0000"
            ),
            XlsCellStyle.BgPink: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="FFC0CB"
            ),
            XlsCellStyle.BgSkyBlueL: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="C5D9F1"
            ),
            XlsCellStyle.BgPurpleL: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="E4DFEC"
            ),
            XlsCellStyle.BgPeachL: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="F2DCDB"
            ),
            XlsCellStyle.BgLightBlue: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="ADD8E6"
            ),
            XlsCellStyle.BgLightGray: ExcelStyle(
                font_color="000000",
                font_bold=False,
                bg_color="D3D3D3"
            ),
            XlsCellStyle.FgRed: ExcelStyle(
                font_color="FF0000",
                font_bold=False,
                bg_color=None
            ),
        }
    
    def create(self, filepath: Path) -> bool:
        """Excel 파일 생성"""
        if Workbook is None:
            raise ImportError("openpyxl is required")
        
        try:
            self.workbook = Workbook()
            self.worksheet = self.workbook.active
            self.worksheet.title = "Sheet1"
            self.filepath = Path(filepath)
            self._hide_gridlines()
            return True
        except Exception as e:
            print(f"Excel create error: {e}")
            return False
    
    def select_sheet(self, sheet_index: int, sheet_name: str, add_if_missing: bool = False) -> bool:
        """시트 선택"""
        if not self.workbook:
            return False
        
        try:
            if add_if_missing and sheet_index > len(self.workbook.worksheets):
                for i in range(len(self.workbook.worksheets), sheet_index):
                    self.workbook.create_sheet(f"Sheet{i + 1}")
            
            if sheet_index <= len(self.workbook.worksheets):
                self.worksheet = self.workbook.worksheets[sheet_index - 1]
                if sheet_name:
                    self.worksheet.title = sheet_name
                return True
        except Exception as e:
            print(f"Select sheet error: {e}")
            return False
    
    def write_data(self, row: int, col: int, data: Any) -> None:
        """셀에 데이터 쓰기"""
        if not self.worksheet or row < 1 or col < 1:
            return
        
        cell = self.worksheet.cell(row=row, column=col)
        if isinstance(data, (int, float)):
            cell.value = data
        elif isinstance(data, bool):
            cell.value = data
        else:
            cell.value = str(data) if data is not None else ""
    
    def apply_style(self, row_start: int, col_start: int, row_end: int, col_end: int, style: XlsCellStyle) -> None:
        """스타일 적용"""
        if not self.worksheet or style == XlsCellStyle.NONE:
            return
        
        style_info = self._styles.get(style)
        if not style_info:
            return
        
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                cell = self.worksheet.cell(row=row, column=col)
                
                # 폰트 설정
                font = Font(
                    name="Arial",
                    size=self.FONTSIZE_DEFAULT,
                    bold=style_info.font_bold,
                    color=style_info.font_color
                )
                cell.font = font
                
                # 배경색 설정
                if style_info.bg_color:
                    fill = PatternFill(start_color=style_info.bg_color, end_color=style_info.bg_color, fill_type="solid")
                    cell.fill = fill
                
                # 정렬 설정
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                
                # 테두리 설정
                if style_info.border:
                    thin_border = Border(
                        left=Side(style="thin", color="000000"),
                        right=Side(style="thin", color="000000"),
                        top=Side(style="thin", color="000000"),
                        bottom=Side(style="thin", color="000000")
                    )
                    cell.border = thin_border
    
    def merge(self, row_start: int, col_start: int, row_end: int, col_end: int) -> None:
        """셀 병합"""
        if not self.worksheet:
            return
        
        start_cell = f"{get_column_letter(col_start)}{row_start}"
        end_cell = f"{get_column_letter(col_end)}{row_end}"
        self.worksheet.merge_cells(f"{start_cell}:{end_cell}")
    
    def set_column_width(self, col: int, width: int) -> None:
        """열 너비 설정"""
        if not self.worksheet:
            return
        
        col_letter = get_column_letter(col)
        self.worksheet.column_dimensions[col_letter].width = width / 7.0  # Excel 단위 변환
    
    def set_row_height(self, row: int, height: int) -> None:
        """행 높이 설정"""
        if not self.worksheet:
            return
        
        self.worksheet.row_dimensions[row].height = height
    
    def set_wrap_text(self, row_start: int, col_start: int, row_end: int, col_end: int, wrap: bool = True) -> None:
        """텍스트 줄바꿈 설정"""
        if not self.worksheet:
            return
        
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                cell = self.worksheet.cell(row=row, column=col)
                cell.alignment = Alignment(wrap_text=wrap, horizontal="center", vertical="center")
    
    def add_comment(self, row: int, col: int, message: str) -> None:
        """주석 추가"""
        if not self.worksheet or not message:
            return
        
        cell = self.worksheet.cell(row=row, column=col)
        cell.comment = Comment(message, "TResultParser")
    
    def draw_double_border(self, row_start: int, col_start: int, row_end: int, col_end: int, edge: BorderEdge, color: str = "000000") -> None:
        """이중 테두리 그리기"""
        if not self.worksheet:
            return
        
        double_side = Side(style="double", color=color)
        
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                cell = self.worksheet.cell(row=row, column=col)
                border = cell.border or Border()
                
                if edge == BorderEdge.Top:
                    border.top = double_side
                elif edge == BorderEdge.Bottom:
                    border.bottom = double_side
                elif edge == BorderEdge.Left:
                    border.left = double_side
                elif edge == BorderEdge.Right:
                    border.right = double_side
                
                cell.border = border
    
    def draw_thick_border(self, row_start: int, col_start: int, row_end: int, col_end: int, edge: BorderEdge, color: str = "000000") -> None:
        """굵은 테두리 그리기"""
        if not self.worksheet:
            return
        
        thick_side = Side(style="thick", color=color)
        
        for row in range(row_start, row_end + 1):
            for col in range(col_start, col_end + 1):
                cell = self.worksheet.cell(row=row, column=col)
                border = cell.border or Border()
                
                if edge == BorderEdge.Top:
                    border.top = thick_side
                elif edge == BorderEdge.Bottom:
                    border.bottom = thick_side
                elif edge == BorderEdge.Left:
                    border.left = thick_side
                elif edge == BorderEdge.Right:
                    border.right = thick_side
                
                cell.border = border
    
    def close(self, save: bool = True) -> bool:
        """Excel 파일 저장 및 닫기"""
        if not self.workbook or not self.filepath:
            return False
        
        try:
            if save:
                self.workbook.save(str(self.filepath))
            return True
        except Exception as e:
            print(f"Excel close error: {e}")
            return False
    
    def _hide_gridlines(self) -> None:
        """그리드 라인 숨기기"""
        if self.worksheet:
            self.worksheet.sheet_view.showGridLines = False


def generate_testcase_excel(tcbank: TCBank, output_path: Path, mode: str = "TestCase") -> bool:
    """테스트 케이스 Excel 리포트 생성
    
    Args:
        tcbank: 파싱된 테스트 케이스 데이터
        output_path: 출력 파일 경로
        mode: 리포트 모드 ("TestCase", "TestResult", "TestReport")
    
    Returns:
        성공 여부
    """
    if Workbook is None:
        raise ImportError("openpyxl is required")
    
    excel = XlsxManager()
    if not excel.create(output_path):
        return False
    
    col_offset = 2
    row_offset = 6
    
    # 제목 생성
    title = f"VectorCAST {mode} Report"
    if tcbank.component_name:
        title = f"{title} - {tcbank.component_name}"
    
    excel.write_data(1, 1, title)
    excel.apply_style(1, 1, 1, excel.XLS_TITLE_COLCOUNT, XlsCellStyle.Title)
    excel.merge(1, 1, 1, excel.XLS_TITLE_COLCOUNT)
    excel.set_row_height(1, 40)
    excel.set_column_width(1, 1)
    
    # 데이터 행 생성
    current_row = row_offset
    col_count = 0
    
    if mode == "TestCase":
        # TestCase 모드: TC Index, TC ID, Unit Name, TC Gen Method, Input, Expected Result, Related ID
        headers = ["TC Index", "TC ID", "Unit Name", "TC Gen Method"]
        col_count = len(headers) + len(tcbank.input_names) + len(tcbank.exp_result_names) + 1
        
        # 헤더 행
        col = col_offset
        for h in headers:
            excel.write_data(current_row, col, h)
            col += 1
        
        # Input 헤더
        if tcbank.input_names:
            excel.write_data(current_row, col, "Input")
            excel.merge(current_row, col, current_row, col + len(tcbank.input_names) - 1)
            col += len(tcbank.input_names)
        
        # Expected Result 헤더
        if tcbank.exp_result_names:
            excel.write_data(current_row, col, "Expected Result")
            excel.merge(current_row, col, current_row, col + len(tcbank.exp_result_names) - 1)
            col += len(tcbank.exp_result_names)
        
        # Related ID 헤더
        excel.write_data(current_row, col, "Related ID")
        excel.merge(current_row, col, current_row + 1, col)
        
        excel.apply_style(current_row, col_offset, current_row, col_offset + col_count - 1, XlsCellStyle.Caption)
        current_row += 1
        
        # 데이터 행
        tc_index = 0
        for tc_name, tc_items in sorted(tcbank.test_cases.items()):
            for tc_item in tc_items:
                tc_index += 1
                col = col_offset
                
                excel.write_data(current_row, col, tc_index)
                col += 1
                excel.write_data(current_row, col, tc_item.header.test_case_name)
                col += 1
                excel.write_data(current_row, col, tc_item.header.unit_name)
                col += 1
                excel.write_data(current_row, col, "")  # TC Gen Method
                col += 1
                
                # Input 데이터
                for input_name in tcbank.input_names:
                    value = tc_item.input_data.get(input_name, "")
                    excel.write_data(current_row, col, value)
                    col += 1
                
                # Expected Result 데이터
                for exp_name in tcbank.exp_result_names:
                    value = tc_item.expected_result.get(exp_name, "")
                    excel.write_data(current_row, col, value)
                    col += 1
                
                # Related ID
                excel.write_data(current_row, col, "")
                
                excel.set_wrap_text(current_row, col_offset, current_row, col_offset + col_count - 1, True)
                current_row += 1
    
    elif mode == "TestResult":
        # TestResult 모드: TC Index, TC ID, Actual Result, Pass/Fail, Memo
        headers = ["TC Index", "TC ID"]
        col_count = len(headers) + len(tcbank.act_result_names) + 3  # Actual Result + Pass/Fail + Memo
        
        # 헤더 행
        col = col_offset
        for h in headers:
            excel.write_data(current_row, col, h)
            col += 1
        
        # Actual Result 헤더
        if tcbank.act_result_names:
            excel.write_data(current_row, col, "Actual Result")
            excel.merge(current_row, col, current_row, col + len(tcbank.act_result_names) - 1)
            col += len(tcbank.act_result_names)
        
        # Pass/Fail 헤더
        excel.write_data(current_row, col, "Pass/Fail")
        excel.merge(current_row, col, current_row, col + 1)
        col += 2
        
        # Memo 헤더
        excel.write_data(current_row, col, "Memo")
        
        excel.apply_style(current_row, col_offset, current_row, col_offset + col_count - 1, XlsCellStyle.Caption)
        current_row += 1
        
        # 데이터 행
        tc_index = 0
        for tc_name, tr_items in sorted(tcbank.test_results.items()):
            for tr_item in tr_items:
                tc_index += 1
                col = col_offset
                
                excel.write_data(current_row, col, tc_index)
                col += 1
                excel.write_data(current_row, col, tr_item.header.test_case_name)
                col += 1
                
                # Actual Result 데이터
                for act_name in tcbank.act_result_names:
                    if act_name in tr_item.actual_result:
                        actual, expected = tr_item.actual_result[act_name]
                        excel.write_data(current_row, col, actual)
                    else:
                        excel.write_data(current_row, col, "")
                    col += 1
                
                # Pass/Fail
                pass_fail = "PASS" if tr_item.passed else "FAIL"
                excel.write_data(current_row, col, pass_fail)
                excel.merge(current_row, col, current_row, col + 1)
                col += 2
                
                # Memo
                excel.write_data(current_row, col, "")
                
                excel.set_wrap_text(current_row, col_offset, current_row, col_offset + col_count - 1, True)
                current_row += 1
    
    # 테이블 포맷 설정
    _set_table_format(excel, col_offset, row_offset, current_row - 1, col_count)
    
    # 열 너비 설정
    for col in range(col_offset, col_offset + col_count):
        excel.set_column_width(col, 15)
    
    return excel.close(True)


def _set_table_format(excel: XlsxManager, col_offset: int, row_offset: int, last_row: int, col_count: int) -> None:
    """테이블 포맷 설정"""
    row_start = row_offset - 1
    row_last = last_row
    col_last = col_offset + col_count - 1
    
    # 테두리 그리기
    excel.draw_thick_border(row_start, col_offset, row_start, col_last, BorderEdge.Top)
    excel.draw_double_border(row_start + 2, col_offset, row_start + 2, col_last, BorderEdge.Top)
    excel.draw_double_border(row_last, col_offset, row_last, col_last, BorderEdge.Top)
    
    excel.draw_thick_border(row_start, col_offset, row_last, col_offset, BorderEdge.Left)
    excel.draw_thick_border(row_start, col_last, row_last, col_last, BorderEdge.Right)
    excel.draw_thick_border(row_last, col_offset, row_last, col_last, BorderEdge.Bottom)


def generate_metrics_excel(metrics_bank: MetricsBank, output_path: Path, unit_bank: Optional[Dict[str, str]] = None) -> bool:
    """Metrics Excel 리포트 생성
    
    Args:
        metrics_bank: 파싱된 Metrics 데이터
        output_path: 출력 파일 경로
        unit_bank: Unit ID 매핑 (선택사항)
    
    Returns:
        성공 여부
    """
    if Workbook is None:
        raise ImportError("openpyxl is required")
    
    excel = XlsxManager()
    if not excel.create(output_path):
        return False
    
    col_offset = 1
    row_offset = 3
    
    # UT Matrics 시트 (Statement)
    if metrics_bank.statement_data:
        excel.select_sheet(1, "UT Matrics", True)
        _generate_ut_metrics_sheet(excel, metrics_bank.statement_data, unit_bank, col_offset, row_offset)
    
    # IT Matrics 시트 (Functions)
    if metrics_bank.functions_data:
        sheet_num = 2 if metrics_bank.statement_data else 1
        excel.select_sheet(sheet_num, "IT Matrics", True)
        _generate_it_metrics_sheet(excel, metrics_bank.functions_data, unit_bank, col_offset, row_offset)
    
    return excel.close(True)


def _generate_ut_metrics_sheet(
    excel: XlsxManager,
    statement_data: Dict[str, MatixDataBank],
    unit_bank: Optional[Dict[str, str]],
    col_offset: int,
    row_offset: int
) -> None:
    """UT Matrics 시트 생성"""
    # 헤더
    headers = [
        "No", "TestID", "UnitID", "SubProgram", "Complexity",
        "Stat(Cnt)", "Stat(TTL)", "Stat(%)",
        "Branch(Cnt)", "Branch(TTL)", "Branch(%)",
        "ITS Called", "FCalls(Cnt)", "FCalls(TTL)", "FCalls(%)"
    ]
    
    current_row = row_offset
    col_count = len(headers)
    
    # 헤더 행
    for col, header in enumerate(headers, start=col_offset):
        excel.write_data(current_row, col, header)
    
    excel.apply_style(current_row, col_offset, current_row, col_offset + col_count - 1, XlsCellStyle.Caption)
    current_row += 1
    
    # 데이터 행
    row_num = 1
    statement_total = MatricStatementItem()
    statement_total.statements = CoverageItem("")
    statement_total.branches = CoverageItem("")
    statement_total.functions_call = CoverageItem("")
    
    for unit_name, bank in sorted(statement_data.items()):
        count = 0
        root_row = current_row
        
        for subprogram, item in sorted(bank.dic_data.items()):
            if not isinstance(item, MatricStatementItem):
                continue
            
            is_root = count == 0
            excel.write_data(current_row, col_offset, row_num)
            
            # TestID
            excel.write_data(current_row, col_offset + 1, item.id if is_root else "")
            
            # UnitID
            unit_id = ""
            if unit_bank and item.subprogram:
                func_name_lower = item.subprogram.lower()
                for uid, fname in unit_bank.items():
                    if fname.lower() == func_name_lower:
                        unit_id = uid
                        break
            excel.write_data(current_row, col_offset + 2, unit_id)
            
            # SubProgram
            excel.write_data(current_row, col_offset + 3, item.subprogram)
            
            # Complexity
            excel.write_data(current_row, col_offset + 4, item.complexity)
            
            # Statements
            if item.statements:
                excel.write_data(current_row, col_offset + 5, item.statements.count)
                excel.write_data(current_row, col_offset + 6, item.statements.total)
                excel.write_data(current_row, col_offset + 7, item.statements.percentage)
                
                statement_total.statements.count += item.statements.count
                statement_total.statements.total += item.statements.total
            
            # Branches
            if item.branches:
                excel.write_data(current_row, col_offset + 8, item.branches.count)
                excel.write_data(current_row, col_offset + 9, item.branches.total)
                excel.write_data(current_row, col_offset + 10, item.branches.percentage)
                
                statement_total.branches.count += item.branches.count
                statement_total.branches.total += item.branches.total
            
            # ITS Called
            excel.write_data(current_row, col_offset + 11, "O" if item.is_function else "X")
            
            # Function Calls
            if item.functions_call:
                excel.write_data(current_row, col_offset + 12, item.functions_call.count)
                excel.write_data(current_row, col_offset + 13, item.functions_call.total)
                excel.write_data(current_row, col_offset + 14, item.functions_call.percentage)
                
                statement_total.functions_call.count += item.functions_call.count
                statement_total.functions_call.total += item.functions_call.total
            
            excel.set_wrap_text(current_row, col_offset, current_row, col_offset + col_count - 1, True)
            current_row += 1
            row_num += 1
            count += 1
    
    # Total 행
    excel.write_data(current_row, col_offset + 1, "Total")
    if statement_total.statements:
        excel.write_data(current_row, col_offset + 5, statement_total.statements.count)
        excel.write_data(current_row, col_offset + 6, statement_total.statements.total)
        excel.write_data(current_row, col_offset + 7, statement_total.statements.percentage)
    if statement_total.branches:
        excel.write_data(current_row, col_offset + 8, statement_total.branches.count)
        excel.write_data(current_row, col_offset + 9, statement_total.branches.total)
        excel.write_data(current_row, col_offset + 10, statement_total.branches.percentage)
    if statement_total.functions_call:
        excel.write_data(current_row, col_offset + 12, statement_total.functions_call.count)
        excel.write_data(current_row, col_offset + 13, statement_total.functions_call.total)
        excel.write_data(current_row, col_offset + 14, statement_total.functions_call.percentage)
    
    # 제목 행
    excel.write_data(1, 1, "UT Matrics")
    excel.apply_style(1, 1, 1, col_count, XlsCellStyle.Title)
    excel.merge(1, 1, 1, col_count)
    
    # 열 너비 설정
    for col in range(col_offset, col_offset + col_count):
        excel.set_column_width(col, 15)


def _generate_it_metrics_sheet(
    excel: XlsxManager,
    functions_data: Dict[str, MatixDataBank],
    unit_bank: Optional[Dict[str, str]],
    col_offset: int,
    row_offset: int
) -> None:
    """IT Matrics 시트 생성"""
    # 헤더
    headers = ["No", "Unit", "UnitID", "SubProgram", "Complexity", "Functions", "Function Calls"]
    
    current_row = row_offset
    col_count = len(headers)
    
    # 헤더 행
    for col, header in enumerate(headers, start=col_offset):
        excel.write_data(current_row, col, header)
    
    excel.apply_style(current_row, col_offset, current_row, col_offset + col_count - 1, XlsCellStyle.Caption)
    current_row += 1
    
    # 데이터 행
    row_num = 1
    funcall_total = MatricFunCallItem()
    funcall_total.functions = CoverageItem("")
    funcall_total.functions_call = CoverageItem("")
    
    for unit_name, bank in sorted(functions_data.items()):
        for subprogram, item in sorted(bank.dic_data.items()):
            if not isinstance(item, MatricFunCallItem):
                continue
            
            excel.write_data(current_row, col_offset, row_num)
            
            # Unit
            excel.write_data(current_row, col_offset + 1, item.unit_name)
            
            # UnitID
            unit_id = ""
            if unit_bank and item.subprogram:
                func_name_lower = item.subprogram.lower()
                for uid, fname in unit_bank.items():
                    if fname.lower() == func_name_lower:
                        unit_id = uid
                        break
            excel.write_data(current_row, col_offset + 2, unit_id)
            
            # SubProgram
            excel.write_data(current_row, col_offset + 3, item.subprogram)
            
            # Complexity
            excel.write_data(current_row, col_offset + 4, item.complexity)
            
            # Functions
            if item.functions:
                excel.write_data(current_row, col_offset + 5, item.functions.coverage)
                funcall_total.functions.count += item.functions.count
                funcall_total.functions.total += item.functions.total
            
            # Function Calls
            if item.functions_call:
                excel.write_data(current_row, col_offset + 6, item.functions_call.coverage)
                funcall_total.functions_call.count += item.functions_call.count
                funcall_total.functions_call.total += item.functions_call.total
            
            excel.set_wrap_text(current_row, col_offset, current_row, col_offset + col_count - 1, True)
            current_row += 1
            row_num += 1
    
    # Total 행
    excel.write_data(current_row, col_offset + 1, "Total")
    if funcall_total.functions:
        excel.write_data(current_row, col_offset + 5, funcall_total.functions.coverage)
    if funcall_total.functions_call:
        excel.write_data(current_row, col_offset + 6, funcall_total.functions_call.coverage)
    
    # 제목 행
    excel.write_data(1, 1, "IT Matrics")
    excel.apply_style(1, 1, 1, col_count, XlsCellStyle.Title)
    excel.merge(1, 1, 1, col_count)
    
    # 열 너비 설정
    for col in range(col_offset, col_offset + col_count):
        excel.set_column_width(col, 15)
