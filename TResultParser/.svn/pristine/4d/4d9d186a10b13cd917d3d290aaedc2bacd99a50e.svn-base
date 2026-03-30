using ClosedXML.Excel;
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;

namespace TResultParser.Lib.Component {
    public class XlsxManager {

        #region variables
        #region enum
        public enum XlsCellStyle {
            Title = 0,// BgNavyFWhiteB = 0,
            Caption, // 0xF7EBDD
            General,
            Fixed,
            BgSkyBlue,
            BgYellow,
            BgOrange,
            BgRed,
            BgPink,
            BgSkyBlueL,
            BgPurpleL,
            BgPeachL,

            BgLightBlue,
            BgLightGray,
            BgPinkFRed,
            BgBlueFRed,
            FgRed,
            None,
        }

        public enum BorderEdge {
            Left = 0,
            Right,
            Top,
            Bottom,
            None,
        }
        #endregion

        private const int FONTSIZE_DEFAULT = 10;

        private XLWorkbook m_xlsWorkBook;
        private IXLWorksheet m_xlsWookSheet;
        private string m_sFilePath;

        #endregion

        #region Constructor
        public XlsxManager()
        {
            init();
        }

        private void init()
        {
            m_xlsWorkBook = null;
            m_xlsWookSheet = null;
        }
        #endregion

        #region File Open/Close
        public bool create(string sFilePath)
        {
            init();

            m_sFilePath = sFilePath;

            try { 
                m_xlsWorkBook = new XLWorkbook();
                m_xlsWorkBook.Style.Font.FontName = "Arial";
                m_xlsWorkBook.Style.Font.FontSize = FONTSIZE_DEFAULT;

                m_xlsWookSheet = m_xlsWorkBook.Worksheets.Add("Sheet1");
            }
            catch (Exception ex) {
                Debug.Print("excel.Create error :{0}", ex.Message);
                return false;
            }

            hideGridLine();
     //       buildStyle();
            return true;
        }

        public bool open(string filepath)
        {
            init();
            m_sFilePath = filepath;
            try {
                m_xlsWorkBook = new XLWorkbook(filepath);
                //                m_xlsWorkBook.Style.Font.FontName = "Arial";
                //                m_xlsWorkBook.Style.Font.FontSize = FONTSIZE_DEFAULT;

                m_xlsWookSheet = m_xlsWorkBook.Worksheet(1);

            }
            catch (Exception ex) {
                Debug.Print("excel.Open error :{0}", ex.Message);
                return false;
            }

//            hideGridLine();
            return true;
        }

        public bool close(bool savechanges, bool boSortReverse = true)
        {
            try {
                if (boSortReverse) {
                    sortSheetReverse();
                }

                if (m_xlsWorkBook != null) {
                    m_xlsWorkBook.SaveAs(m_sFilePath);
                }

            }
            catch (Exception ex) {
                Debug.Print("excel.Close error : HResult = 0x{0:X} , {1}", ex.HResult, ex.Message);
            }

            init();
            return true;
        }

        public bool save()
        {
            try {
                if (m_xlsWorkBook != null) {
                    m_xlsWorkBook.SaveAs(m_sFilePath);
                }
            }
            catch (Exception ex) {
                Debug.Print("excel.save error : HResult = 0x{0:X} , {1}", ex.HResult, ex.Message);
                return false;
            }

            return true;
        }

        public void execute(string sFilePath)
        {
            if (File.Exists(sFilePath)) {
                System.Diagnostics.Process.Start(sFilePath);
            }
        }
        #endregion

        #region Read, Write Cell
        public void writeData(int row, int col, object data)
        {
            if (m_xlsWookSheet == null || row < 1 || col < 1 || data == null) {
                return;
            }

            IXLCell cell = cvrtToCell(row, col);
            if (cell == null) {
                return;
            }

            //  IEquatable<XLCellValue>, IEquatable<Blank>, IEquatable<bool>, IEquatable<double>, IEquatable<string>, IEquatable<XLError>, 
            // IEquatable<DateTime>, IEquatable<TimeSpan>, IEquatable<int>
            if (data.GetType() == typeof(bool)) {
                cell.Value = (bool)data;
            }

            if (data.GetType() == typeof(double)) {
                cell.Value = (double)data;
            }

            if (data.GetType() == typeof(float)) {
                cell.Value = (double)(float)data;
            }

            if (data.GetType() == typeof(string)) {
                cell.Value = (string)data;
            }

            if (data.GetType() == typeof(DateTime)) {
                cell.Value = (DateTime)data;
            }

            if (data.GetType() == typeof(TimeSpan)) {
                cell.Value = (TimeSpan)data;
            }

            if (data.GetType() == typeof(int)) {
                cell.Value = (int)data;
            }
        }

        public void writeColums(int row, int column, params string[] data)
        {
            if (m_xlsWookSheet == null || row < 1 || column < 1 || data == null || data.Length == 0) {
                return;
            }

            for (int idx = 0; idx < data.Length; idx++) {
                m_xlsWookSheet.Cell(row + idx, column).Value = data[idx];
            }
        }

        public void writeRows(int row, int column, params string[] data)
        {
            if (m_xlsWookSheet == null || row < 1 || column < 1 || data == null || data.Length == 0) {
                return;
            }

            for (int idx = 0; idx < data.Length; idx++) {
                m_xlsWookSheet.Cell(row, column + idx).Value = data[idx];
            }
        }

        public object readData(int row, int column)
        {
            if (m_xlsWookSheet == null || row < 1 || column < 1) {
                return null;
            }

            return m_xlsWookSheet.Cell(row, column).Value;
        }

        public string readDataAsText(int row, int column)
        {
            object data = readData(row, column);
            if (data == null) {
                return string.Empty;
            }

            return data.ToString();
        }
        #endregion

        #region comment
        public void addComment(int row, int column, string message)
        {
            if (m_xlsWookSheet == null || row < 1 || column < 1 || string.IsNullOrEmpty(message)) {
                return;
            }

            var comment = m_xlsWookSheet.Cell(row, column).CreateComment();// .AddComment(message);
            comment.AddText(message);
            comment.Visible = true;
        }
        #endregion

        #region sheet
        public bool selectSheet(string sheetname)
        {
            if (m_xlsWorkBook == null || string.IsNullOrEmpty(sheetname)) {
                return false;
            }

            if (m_xlsWorkBook.Worksheets.Contains(sheetname)) {
                m_xlsWookSheet = m_xlsWorkBook.Worksheet(sheetname);
                return true;
            }
            return false;
        }

        public bool selectSheet(int sheetindex)
        {
            if (m_xlsWorkBook == null || sheetindex < 1) {
                return false;
            }

            if (sheetindex <= m_xlsWorkBook.Worksheets.Count) {
                m_xlsWookSheet = m_xlsWorkBook.Worksheet(sheetindex);
                return true;
            }
            return false;
        }

        public bool selectSheet(int sheetindx, string sheetname, bool boAdd)
        {
            if (m_xlsWorkBook == null) {
                return false;
            }

            if (boAdd && (sheetindx > m_xlsWorkBook.Worksheets.Count)) {
                for (int iIdx = m_xlsWorkBook.Worksheets.Count; iIdx < sheetindx; iIdx++) {
                    addSheet(string.Format("sheet{0}", iIdx));
                }
      //          sheetindx = 1; // Last Sheet
            }

            m_xlsWookSheet = m_xlsWorkBook.Worksheet(sheetindx);
            m_xlsWookSheet.Select();

            if (!string.IsNullOrEmpty(sheetname) && m_xlsWookSheet.Name != sheetname) {
                m_xlsWookSheet.Name = sheetname;
            }

            hideGridLine();
            return true;
        }

        public bool addSheet(string sheetname)
        {
            if (m_xlsWorkBook == null || string.IsNullOrEmpty(sheetname)) {
                return false;
            }

            m_xlsWorkBook.AddWorksheet(sheetname);
            return true;
        }

        private void DEBUG_SheetNames()
        {
            string Name = string.Empty;
            for (int idx = 1; idx <= m_xlsWorkBook.Worksheets.Count; idx++) {
                Name += string.Format("{0}, ", m_xlsWorkBook.Worksheet(idx).Name);
            }
            Debug.Print("Sheets : {0}", Name);
        }

        public bool sortSheetReverse()
        {
            if (m_xlsWorkBook == null) {
                return false;
            }
/*
            var sheetNames = Enumerable.Range(1, 5).Select(i => $"Sheet{i}").Reverse();

            // Add sheets to the workbook in reversed order
            foreach (var sheetName in sheetNames) {
                var worksheet = workbook.Worksheets.Add(sheetName);
                // Add some data to each sheet
                worksheet.Cell(1, 1).Value = $"Data in {sheetName}";
            }
*/
            return true;
        }

        private bool deleteSheet(int sheetindex)
        {
            if (m_xlsWorkBook == null || sheetindex < 1) {
                return false;
            }

            if (sheetindex >= m_xlsWorkBook.Worksheets.Count) {
                return false;
            }

            m_xlsWorkBook.Worksheet(sheetindex).Delete();
            return true;
        }

        public int sheetCount()
        {
            return m_xlsWorkBook.Worksheets.Count;
        }
        #endregion

        #region Column, Row
        public int getColumnMaxCount()
        {
            if (m_xlsWookSheet == null) {
                return -1;
            }

            return m_xlsWookSheet.RangeUsed().ColumnCount();
        }

        public int getRowMaxCount()
        {
            if (m_xlsWookSheet == null) {
                return -1;
            }

            return m_xlsWookSheet.RangeUsed().RowCount();
        }
        #endregion

        #region Range
        //-------------------------------------------------------------------------
        // Range 
        //-------------------------------------------------------------------------
        public IXLCell cvrtToCell(int row, int col)
        {
            if (m_xlsWookSheet == null || row < 1 || col < 1) {
                return null;
            }

            return m_xlsWookSheet.Cell(row, col);
        }

        public IXLRange cvrtToRange(int row, int col)
        {
            if (m_xlsWookSheet == null || row < 1 || col < 1) {
                return null;
            }

            IXLCell cell = cvrtToCell(row, col);
            if (cell == null) {
                return null;
            }

            return m_xlsWookSheet.Range(cell, cell);
        }

        public string getCellValue(int row, int col)
        {
            if (m_xlsWookSheet == null || row < 1 || col < 1) {
                return string.Empty;
            }

            object data = m_xlsWookSheet.Cell(row, col).Value;
            if (data == null) {
                return string.Empty;
            }

            return data.ToString();
        }

        public IXLRange cvrtToRange(int row_start, int col_start, int row_end, int col_end)
        {
            if (m_xlsWookSheet == null || row_start < 1 || col_start < 1 || row_end < row_start || col_end < col_start) {
                return null;
            }

            return m_xlsWookSheet.Range(m_xlsWookSheet.Cell(row_start, col_start), m_xlsWookSheet.Cell(row_end, col_end));
        }

        public string cellName(int row, int column)
        {
            if (m_xlsWookSheet == null || row < 1 || column < 1) {
                return null;
            }

            return string.Format("{0}{1}", XLHelper.GetColumnLetterFromNumber(column), row);
        }
/*
        private string getColumnName(int column)
        {
            int dividend = column;
            string sColumnName = string.Empty;
            int modulo;

            while (dividend > 0) {
                modulo = (dividend - 1) % 26;
                sColumnName = Convert.ToChar(65 + modulo).ToString() + sColumnName;
                dividend = (int)((dividend - modulo) / 26);
            }

            return sColumnName;
        }
*/
        #endregion

        #region Format
        public void hideGridLine()
        {
            if (m_xlsWookSheet == null) {
                return;
            }

            m_xlsWookSheet.ShowGridLines = false;
        }

        //-------------------------------------------------------------------------
        // Cell format 
        //-------------------------------------------------------------------------
        public void setCellFormatAsText(int row_start, int col_start, int row_end, int col_end)
        {
            setCellFormatAsText(cvrtToRange(row_start, col_start, row_end, col_end));
        }

        public void setCellFormatAsText(IXLRange cellRange)
        {
            if (cellRange == null) {
                return;
            }

            foreach (var cell in cellRange.CellsUsed()) {
                cell.Value = cell.Value.ToString();
            }
        }

        public void setCellFormatAsPercent(int row_start, int col_start, int row_end, int col_end)
        {
            setCellFormatAsPercent(cvrtToRange(row_start, col_start, row_end, col_end));
        }

        public void setCellFormatAsPercent(IXLRange cellRange)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.NumberFormat.Format = "0%";
//            cellRange.NumberFormat = "###.##%";
        }

        public void setBorder(int row_start, int col_start, int row_end, int col_end, BorderEdge edge, XLBorderStyleValues style, XLColor color)
        {
            setBorder(cvrtToRange(row_start, col_start, row_end, col_end), edge, style, color);
        }

        public void setBorder(IXLRange cellRange, BorderEdge edge, XLBorderStyleValues style, XLColor color)
        {
            if (cellRange == null) {
                return;
            }

            switch (edge) {
                case BorderEdge.Left: {
                        cellRange.Style.Border.LeftBorder = style;
                        cellRange.Style.Border.LeftBorderColor = color;
                    }break;
                case BorderEdge.Right: {
                        cellRange.Style.Border.RightBorder = style;
                        cellRange.Style.Border.RightBorderColor = color;
                    }
                    break;
                case BorderEdge.Top: {
                        cellRange.Style.Border.TopBorder = style;
                        cellRange.Style.Border.TopBorderColor = color;
                    }
                    break;
                case BorderEdge.Bottom: {
                        cellRange.Style.Border.BottomBorder = style;
                        cellRange.Style.Border.BottomBorderColor = color;
                    }
                    break;

            }
        }

        public void setBorderAll(int row_start, int col_start, int row_end, int col_End, XLBorderStyleValues style, XLColor color)
        {
            setBorderAll(cvrtToRange(row_start, col_start, row_end, col_End), style, color);
        }

        public void setBorderAll(IXLRange cellRange, XLBorderStyleValues style, XLColor color)
        {
            if (cellRange == null) {
                return;
            }

            setBorder(cellRange, BorderEdge.Left, style, color);
            setBorder(cellRange, BorderEdge.Right, style, color);
            setBorder(cellRange, BorderEdge.Top, style, color);
            setBorder(cellRange, BorderEdge.Bottom, style, color);

        }

        public void setBackgroundColor(int row, int column, XLColor color)
        {
            setBackgroundColor(cvrtToRange(row, column, row, column), color);
        }

        public void setBackgroundColor(int row_start, int col_start, int row_end, int col_end, XLColor color)
        {
            setBackgroundColor(cvrtToRange(row_start, col_start, row_end, col_end), color);
        }

        public void setBackgroundColor(IXLRange cellRange, XLColor color)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Fill.BackgroundColor = color;
        }

        public void merge(int row_start, int col_start, int row_end, int col_end)
        {
            merge(cvrtToRange(row_start, col_start, row_end, col_end));
        }

        public void merge(IXLRange cellRange)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Merge(false);
        }

        //-------------------------------------------------------------------------
        // Alignment
        //-------------------------------------------------------------------------
        public void setAlignHorizontal(int row_start, int col_start, int row_End, int col_End, XLAlignmentHorizontalValues align)
        {
            setAlignHorizontal(cvrtToRange(row_start, col_start, row_End, col_End), align);
        }

        public void setAlignHorizontal(IXLRange cellRange, XLAlignmentHorizontalValues align)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Alignment.Horizontal = align;
        }

        public void setAlignVertical(int row_start, int col_start, int row_End, int col_end, XLAlignmentVerticalValues align)
        {
            setAlignVertical(cvrtToRange(row_start, col_start, row_End, col_end), align);
        }

        public void setAlignVertical(IXLRange cellRange, XLAlignmentVerticalValues align)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Alignment.Vertical = align;
        }

        public void setWrapText(int row_start, int col_start, int row_End, int col_End, bool wraptext)
        {
            setWrapText(cvrtToRange(row_start, col_start, row_End, col_End), wraptext);
        }

        public void setWrapText(IXLRange cellRange, bool wraptext)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Alignment.WrapText = wraptext;
        }
        #endregion

        #region Font 
        public void setFontBold(int row_start, int col_start, int row_end, int col_end)
        {
            setFontBold(cvrtToRange(row_start, col_start, row_end, col_end));
        }
        public void setFontBold(IXLRange cellRange)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Font.Bold = true;
        }

        public void setFontSize(int row_start, int col_start, int row_end, int col_end, int fontsize)
        {
            setFontSize(cvrtToRange(row_start, col_start, row_end, col_end), fontsize);
        }

        public void setFontSize(IXLRange cellRange, int fontsize)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Font.FontSize = fontsize;
        }

        public void setFontColor(int row_start, int col_start, int row_end, int col_end, XLColor color)
        {
            setFontColor(cvrtToRange(row_start, col_start, row_end, col_end), color);
        }

        public void setFontColor(IXLRange cellRange, XLColor color)
        {
            if (cellRange == null) {
                return;
            }

            cellRange.Style.Font.FontColor = color;
        }

        #endregion

        #region CellSize
        public void setColumnWidth(int col, int width)
        {
            if (m_xlsWookSheet == null || col < 1 || col >= m_xlsWookSheet.ColumnCount()) {
                return;
            }

            m_xlsWookSheet.Column(col).Width = width;

        }
        public void setRowHeight(int row, int height)
        {
            if (m_xlsWookSheet == null || row < 1 ) {
                return;
            }

            m_xlsWookSheet.Row(row).Height = height;
        }
        #endregion

        #region Cell Style
        public void drawDoubleBorder(int row_start, int col_start, int row_end, int col_end, BorderEdge edge, XLColor borderColor)
        {
            IXLRange range = cvrtToRange(row_start, col_start, row_end, col_end);
            style_drawDoubleBorder(range, edge, borderColor);
        }

        public void style_drawDoubleBorder(IXLRange range, BorderEdge edge, XLColor borderColor)
        {
            if (range == null ||(edge != BorderEdge.Left && edge != BorderEdge.Right && edge != BorderEdge.Top && edge != BorderEdge.Bottom)) {
                return;
            }

            setBorder(range, edge, XLBorderStyleValues.Double, borderColor);
        }

        public void drawThickBorder(int row_start, int col_start, int row_end, int col_end, BorderEdge edge, XLColor borderColor)
        {
            IXLRange range = cvrtToRange(row_start, col_start, row_end, col_end);
            drawThickBorder(range, edge, borderColor);
        }

        public void drawThickBorder(IXLRange range, BorderEdge edge, XLColor borderColor)
        {
            if (range == null || (edge != BorderEdge.Left && edge != BorderEdge.Right && edge != BorderEdge.Top && edge != BorderEdge.Bottom)) {
                return;
            }

            setBorder(range, edge, XLBorderStyleValues.Thick, borderColor);
        }

        private XLColor style_getFontColor(XlsCellStyle style)
        {
            switch (style) {
                case XlsCellStyle.Title: return XLColor.White;
                case XlsCellStyle.BgPinkFRed:
                case XlsCellStyle.BgBlueFRed:
                case XlsCellStyle.FgRed: return XLColor.Red;
            }

            return XLColor.Black;
        }

        private bool style_IsFontBold(XlsCellStyle style)
        {
            return (style == XlsCellStyle.Title || style == XlsCellStyle.Caption || style == XlsCellStyle.Fixed);
        }

        private XLColor style_getBGColor(XlsCellStyle style)
        {
            switch (style) {
                case XlsCellStyle.Title:        return XLColor.FromArgb(0x203764);// 0x643720
                case XlsCellStyle.Caption:      
                case XlsCellStyle.BgSkyBlue:    return XLColor.FromArgb(0xDDEBF7); // 0xF7EBDD
                case XlsCellStyle.General:      return XLColor.NoColor;
                case XlsCellStyle.Fixed:        return XLColor.FromArgb(0xEEEEEE);
                case XlsCellStyle.BgYellow:     return XLColor.Yellow;
                case XlsCellStyle.BgOrange:     return XLColor.Orange;
                case XlsCellStyle.BgRed:        return XLColor.Red;
                case XlsCellStyle.BgPink:       return XLColor.FromColor(Color.FromArgb(90, Color.LightPink));
                case XlsCellStyle.BgSkyBlueL:   return XLColor.FromArgb(0xC5D9F1); // 0xF1D9C5
                case XlsCellStyle.BgPurpleL:    return XLColor.FromArgb(0xE4DFEC); // 0xECDFE4
                case XlsCellStyle.BgPeachL:     return XLColor.FromArgb(0xF2DCDB); // 0xDBDCF2
                case XlsCellStyle.BgLightBlue:  return XLColor.FromColor(Color.FromArgb(90, Color.LightBlue));
                case XlsCellStyle.BgLightGray:  return XLColor.FromColor(Color.FromArgb(90, Color.LightGray));
                case XlsCellStyle.BgPinkFRed:   return XLColor.FromColor(Color.FromArgb(90, Color.LightPink));
                case XlsCellStyle.BgBlueFRed:   return XLColor.FromColor(Color.FromArgb(90, Color.LightBlue));
                case XlsCellStyle.FgRed:        return XLColor.NoColor;
            }

            return XLColor.NoColor;
        }

        public void applyStyle(int row_start, int col_start, int row_end, int col_end, XlsCellStyle style)
        {
            applyStyle(cvrtToRange(row_start, col_start, row_end, col_end), style);
        }

        public void applyStyle(IXLRange cellRange, XlsCellStyle style)
        {
            if (cellRange == null) {
                return;
            }

            // Font 
            XLColor fontcolor = style_getFontColor(style);
            setFontColor(cellRange, fontcolor);

            if (style_IsFontBold(style)) {
                setFontBold(cellRange);
            }

            XLColor bgcolor = style_getBGColor(style);
            setBackgroundColor(cellRange, bgcolor);

            XLColor bordercolor = XLColor.Black;
            XLBorderStyleValues borderstyle = XLBorderStyleValues.Thin;

            for (BorderEdge edge = BorderEdge.Left; edge <= BorderEdge.Bottom; edge++) {
                setBorder(cellRange, edge, borderstyle, bordercolor);
            }

            setAlignHorizontal(cellRange, XLAlignmentHorizontalValues.Center);
            setAlignVertical(cellRange, XLAlignmentVerticalValues.Center);
        }
        #endregion

        #region Picture 
        public void insertPicture(string imagePath, int row, int col, int heigth, int width)
        {
            if (!File.Exists(imagePath) || m_xlsWookSheet == null) {
                return;
            }

            var picture = m_xlsWookSheet.AddPicture(imagePath);
            if (picture == null) {
                return;
            }

            picture.Width = width;
            picture.Height = heigth;
            picture.MoveTo(row, col);
        }
        #endregion

        #region Hyperlink
        public void insertLinkFile(int row, int col, string path)
        {
            if (string.IsNullOrEmpty(path) || m_xlsWookSheet == null || row < 0 || col < 0) {
                return;
            }

            int iPos = path.LastIndexOf("\\");
            string sTitle = (iPos < 0) ? path : path.Substring(iPos + 1, path.Length - iPos - 1);

            IXLCell cell = cvrtToCell(row, col);
            if (cell == null) {
                return;
            }

            cell.SetHyperlink( new XLHyperlink(path));
        }
        #endregion

    }
}
