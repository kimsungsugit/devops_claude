"""Auto-generated router: excel"""
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
from pathlib import Path

from backend.schemas import (
    ExcelCompareRequest,
)
from backend.services.excel_compare import compare_excel_files, ExcelCompareItem

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
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel compare error: {str(e)}")


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
            except Exception:
                pass
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel compare error: {str(e)}")


