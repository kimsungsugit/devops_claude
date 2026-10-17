"""Auto-generated router: excel"""
import logging
import traceback
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.schemas import (
    ExcelCompareRequest,
)
from backend.services.excel_compare import ExcelCompareItem, compare_excel_files

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/excel/compare")
def excel_compare(req: ExcelCompareRequest) -> Dict[str, Any]:
    """두 Excel 파일 비교"""
    try:
        compare_item = ExcelCompareItem(
            path_source=Path(req.path_source),
            path_target=Path(req.path_target),
            sheet_source=req.sheet_source,
            sheet_target=req.sheet_target
        )
        
        if not compare_item.valid:
            raise HTTPException(status_code=400, detail="Invalid Excel compare parameters")
        
        diffs = compare_excel_files(compare_item)
        
        return {
            "ok": True,
            "diff_count": len(diffs),
            "is_same": len(diffs) == 0,
            "diffs": [
                {
                    "row": diff.row,
                    "column": diff.column,
                    "source_data": diff.source_data,
                    "target_data": diff.target_data
                }
                for diff in diffs
            ]
        }
    
    # ⚠ 위에서 낸 400("Invalid Excel compare parameters")이 아래 `except Exception` 에
    #   먹혀 **500 "Excel compare error: 400: …"** 로 나가고 있었다. 클라이언트는 자기
    #   입력 문제를 서버 장애로 읽고, 모니터링에는 없는 장애가 쌓인다.
    except HTTPException:
        raise
    except Exception:
        # 내부 예외 문자열은 절대경로를 담을 수 있다 — 로그로만 남긴다.
        _logger.error("Excel compare 실패:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Excel 비교 중 오류 발생")


@router.post("/api/excel/compare-upload")
async def excel_compare_upload(
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    sheet_source: int = Query(1),
    sheet_target: int = Query(1),
) -> Dict[str, Any]:
    """업로드된 두 Excel 파일 비교"""
    try:
        import tempfile
        
        # 임시 파일에 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_source:
            source_content = await source_file.read()
            tmp_source.write(source_content)
            tmp_source_path = Path(tmp_source.name)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_target:
            target_content = await target_file.read()
            tmp_target.write(target_content)
            tmp_target_path = Path(tmp_target.name)
        
        try:
            compare_item = ExcelCompareItem(
                path_source=tmp_source_path,
                path_target=tmp_target_path,
                sheet_source=sheet_source,
                sheet_target=sheet_target
            )
            
            if not compare_item.valid:
                raise HTTPException(status_code=400, detail="Invalid Excel files")
            
            diffs = compare_excel_files(compare_item)
            
            return {
                "ok": True,
                "diff_count": len(diffs),
                "is_same": len(diffs) == 0,
                "diffs": [
                    {
                        "row": diff.row,
                        "column": diff.column,
                        "source_data": diff.source_data,
                        "target_data": diff.target_data
                    }
                    for diff in diffs
                ]
            }
        finally:
            # 임시 파일 삭제
            try:
                tmp_source_path.unlink()
                tmp_target_path.unlink()
            except OSError as exc:      # 임시 파일 정리 실패가 본래 결과를 가리면 안 된다
                _logger.debug("임시 비교 파일 정리 실패: %s", exc)

    # ⚠ 위 400("Invalid Excel files")이 여기 먹혀 500 이 되고 있었다 — 같은 파일의
    #   쌍둥이라 한쪽만 고치면 다른 쪽이 남는다.
    except HTTPException:
        raise
    except Exception:
        _logger.error("Excel compare(upload) 실패:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Excel 비교 중 오류 발생")


