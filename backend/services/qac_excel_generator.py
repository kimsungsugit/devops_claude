"""QAC Excel 리포트 생성기

QAC 리포트를 Excel 형식으로 생성합니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from backend.services.qac_parser import QACDataManager, MatrixItem, HISItem
from backend.services.vcast_excel_generator import XlsxManager, XlsCellStyle

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


def generate_qac_excel(qac_manager: QACDataManager, output_path: Path) -> bool:
    """QAC Excel 리포트 생성
    
    Args:
        qac_manager: 파싱된 QAC 데이터
        output_path: 출력 파일 경로
    
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
    title_col_count = 7
    
    excel.select_sheet(1, "QAC Report", True)
    
    # 제목
    excel.write_data(1, 1, "QAC Report")
    excel.apply_style(1, 1, 1, title_col_count, XlsCellStyle.Title)
    excel.merge(1, 1, 1, title_col_count)
    
    # 헤더 설정
    matrix_list = QACDataManager.get_matrix_list()
    col_count = 2 + len(matrix_list) + 1  # Index, Function, Matrix items, File
    
    # 헤더 행 1
    current_row = row_offset
    excel.write_data(current_row, col_offset, "Index")
    excel.write_data(current_row, col_offset + 1, "Function")
    
    col_idx = col_offset + 2
    for matrix in matrix_list:
        title = HISItem.get_title(matrix, True)
        excel.write_data(current_row, col_idx, title)
        col_idx += 1
    
    excel.write_data(current_row, col_idx, "File")
    
    # 헤더 행 2
    current_row += 1
    excel.write_data(current_row, col_offset, "Index")
    excel.write_data(current_row, col_offset + 1, "Function")
    
    col_idx = col_offset + 2
    for matrix in matrix_list:
        title = HISItem.get_title(matrix, False)
        excel.write_data(current_row, col_idx, title)
        col_idx += 1
    
    excel.write_data(current_row, col_idx, "File")
    
    # 헤더 스타일 적용
    excel.apply_style(row_offset, col_offset, row_offset + 1, col_offset + col_count - 1, XlsCellStyle.Caption)
    
    # 데이터 행
    current_row += 1
    row_num = 1
    
    for his_item in qac_manager.list_result:
        col = col_offset
        excel.write_data(current_row, col, row_num)
        col += 1
        excel.write_data(current_row, col, his_item.function_name)
        col += 1
        
        # Matrix 값들
        for matrix in matrix_list:
            value = his_item.get_matrix_value(matrix)
            warning_level = qac_manager.check_warning_level(matrix, value)
            
            excel.write_data(current_row, col, value)
            
            # 경고 레벨에 따른 스타일 적용
            if warning_level == 1:
                excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgYellow)
            elif warning_level == 2:
                excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgOrange)
            elif warning_level == 3:
                excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgRed)
            
            qac_manager.update_spec_over_count(matrix, warning_level)
            col += 1
        
        excel.write_data(current_row, col, his_item.file_name)
        
        excel.set_wrap_text(current_row, col_offset, current_row, col_offset + col_count - 1, True)
        current_row += 1
        row_num += 1
    
    # Total 행들 (경고 레벨별)
    for warn_level in range(1, 4):  # Level 1, 2, 3
        excel.write_data(current_row, col_offset, "Total")
        excel.write_data(current_row, col_offset + 1, f"Level {warn_level}")
        
        col = col_offset + 2
        spec_string = ""
        
        for matrix in matrix_list:
            col_idx = qac_manager.get_column_index_of_matrix_item(matrix)
            if col_idx < 0:
                excel.write_data(current_row, col, "-")
                excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgLightGray)
            else:
                if matrix in qac_manager.dic_spec_over_count:
                    spec = qac_manager.dic_spec_over_count[matrix]
                    if warn_level <= spec.spec_count:
                        count = spec.list_spec[warn_level - 1]
                        excel.write_data(current_row, col, str(count))
                        
                        # 경고 레벨에 따른 스타일
                        if warn_level == 1:
                            excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgYellow)
                        elif warn_level == 2:
                            excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgOrange)
                        elif warn_level == 3:
                            excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgRed)
                        
                        spec_str = qac_manager.get_spec_string(matrix, warn_level)
                        if spec_str:
                            if spec_string:
                                spec_string += ", "
                            spec_string += spec_str
                    else:
                        excel.write_data(current_row, col, "-")
                        excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgLightGray)
                else:
                    excel.write_data(current_row, col, "-")
                    excel.apply_style(current_row, col, current_row, col, XlsCellStyle.BgLightGray)
            
            col += 1
        
        excel.write_data(current_row, col, spec_string)
        excel.apply_style(current_row, col_offset, current_row, col, XlsCellStyle.BgLightGray)
        current_row += 1
    
    # 일반 데이터 스타일 적용
    excel.apply_style(row_offset + 2, col_offset, current_row - 1, col_offset + col_count - 1, XlsCellStyle.General)
    
    # 열 너비 설정
    widths = [80, 300] + [80] * len(matrix_list) + [500]
    for col in range(col_offset, col_offset + col_count):
        if col - col_offset < len(widths):
            excel.set_column_width(col, widths[col - col_offset])
    
    return excel.close(True)
