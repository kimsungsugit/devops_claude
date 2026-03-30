using C1.Win.C1FlexGrid;
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using static TResultParser.Lib.Component.XlsxManager;

namespace TResultParser.Lib.Component {
    public class FlexgidLib {
        public enum FGridStyle {
            BgYellow,
            BgOrange,
            BgRed,
            BgPink,

            BgLightBlue,
            BgLightGray,
            BgLightPurple,
            BgPinkFRed,
            BgBlueFRed,
            FgRed,
            None,
        }

        public FlexgidLib()
        {

        }

        public XlsCellStyle cvrtToExcelStyle(string styelname)
        {
            if (string.IsNullOrEmpty(styelname)) {
                return XlsCellStyle.None;
            }

            FGridStyle fgstyle = FGridStyle.None;
            for (FGridStyle style = FGridStyle.BgYellow; style < FGridStyle.None; style++) {
                if (style.ToString() == styelname) {
                    fgstyle = style;
                    break;
                }
            }

            if (fgstyle == FGridStyle.None) {
                return XlsCellStyle.None;
            }

            switch (fgstyle) {
                case FGridStyle.BgYellow:   return XlsCellStyle.BgYellow;
                case FGridStyle.BgOrange:   return XlsCellStyle.BgOrange;
                case FGridStyle.BgRed:      return XlsCellStyle.BgRed;
                case FGridStyle.BgPink:     return XlsCellStyle.BgPeachL;
                case FGridStyle.BgLightBlue:    return XlsCellStyle.BgSkyBlueL;
                case FGridStyle.BgLightGray:    return XlsCellStyle.BgLightGray;
                case FGridStyle.BgLightPurple:  return XlsCellStyle.BgPurpleL;
                case FGridStyle.BgPinkFRed:     return XlsCellStyle.BgPinkFRed;
                case FGridStyle.BgBlueFRed:     return XlsCellStyle.BgBlueFRed;
                case FGridStyle.FgRed:          return XlsCellStyle.FgRed;
            }
            return XlsCellStyle.None;
        }

        public void init(C1FlexGrid fgrid, string[] captions, int[] width)
        {
            fgrid.Rows.Count = 1;
            fgrid.Cols.Count = captions.Length;
            for (int col = 0; col < captions.Length; col++) {
                fgrid.Cols[col].Width = width[col];
                fgrid[0, col] = captions[col];
                fgrid.Cols[col].TextAlign = TextAlignEnum.CenterCenter;
            }
        }

        public void clear(C1FlexGrid fgrid)
        {
            // clear style
            if (fgrid.Rows.Count > 1) {
                CellRange cellRng = fgrid.GetCellRange(1, 1, fgrid.Rows.Count - 1, fgrid.Cols.Count - 1);
                if (cellRng.Style != null) {
                    cellRng.Style = null;
                }
            }

            fgrid.Rows.Count = 1;

        }

        public void addData(C1FlexGrid fgrid, string[] data, bool showindex)
        {
            if (fgrid.InvokeRequired) {
                fgrid.Invoke(new Action(delegate () {
                    addData_direct(fgrid, data, showindex);
                }));
            }
            else {
                addData_direct(fgrid, data, showindex);
            }
        }

        private void addData_direct(C1FlexGrid fgrid, string[] data, bool showindex)
        {
            int row = fgrid.Rows.Count;
            fgrid.Rows.Add();

            int column = 0;
            for (int index = 0; index < fgrid.Cols.Count; index++) {
                if (showindex && index == 0) {
                    fgrid[row, column] = (row - fgrid.Rows.Count + 1).ToString();
                    column++;
                }

                if (index < data.Length) {
                    return;
                }

                fgrid[row, column] = data[index];
            }
        }

        public bool IsInRange(C1FlexGrid fgrid, int row, int col)
        {
            if (fgrid == null || row < fgrid.Rows.Fixed || row >= fgrid.Rows.Count || col < fgrid.Cols.Fixed || col >= fgrid.Cols.Count) {
                return false;
            }
            return true;
        }

        public List<CellRange> getMergedCellsOnColumns(C1FlexGrid fgrid)
        {
            List<CellRange> list = new List<CellRange>();
            for (int col = 0; col < fgrid.Cols.Count; col++) {
                if (!fgrid.Cols[col].AllowMerging) {
                    continue;
                }

                for (int row = 0; row < fgrid.Rows.Count; row++) {
                    CellRange range = fgrid.GetMergedRange(row, col);
                    if (range.IsSingleCell) {
                        continue;
                    }

                    if (list.FindIndex(x => x.Equals(range)) <0) {
                        list.Add(range);
                    }
                }
            }

            return list;
        }
        #region style
        private Color getBGColor(FGridStyle fgstyle)
        {
            switch (fgstyle) {
                case FGridStyle.BgYellow:   return Color.Yellow;
                case FGridStyle.BgOrange:   return Color.Orange;
                case FGridStyle.BgRed:      return Color.Red;

                case FGridStyle.BgPink:    
                case FGridStyle.BgPinkFRed:     return Color.FromArgb(0x80, Color.LightPink);
                case FGridStyle.BgBlueFRed:     
                case FGridStyle.BgLightBlue:    return Color.FromArgb(0x80, Color.LightSkyBlue);

                case FGridStyle.BgLightGray:    return Color.FromArgb(0x80, Color.LightGray);
                case FGridStyle.BgLightPurple:  return Color.FromArgb(0x80, Color.MediumPurple);
            }

            return Color.White;
        }

        public void createStyle(C1FlexGrid fgrid)
        {
            for (FGridStyle style = FGridStyle.BgYellow; style <= FGridStyle.FgRed; style++) {
                CellStyle csStyle = fgrid.Styles.Add(style.ToString());

                csStyle.DataType = typeof(string);
                Color bgcolor = getBGColor(style);
                if (bgcolor != Color.White) {
                    csStyle.BackColor = bgcolor;
                }

                if (style >= FGridStyle.BgPinkFRed) {
                    csStyle.ForeColor = Color.Red;
                }
            }
        }

        public void applyStyleOnRow(C1FlexGrid fgrid, FGridStyle fgstyle, int row)
        {
            int col = 0;
            if (!IsInRangeOfRow(fgrid, row)) {
                return;
            }

            CellRange cellRng = fgrid.GetCellRange(row, col, row, fgrid.Cols.Count - 1);
            cellRng.Style = fgrid.Styles[fgstyle.ToString()];
        }

        public void applyStyle(C1FlexGrid fgrid, FGridStyle fgstyle, int row, int col)
        {
            if (!IsInRange(fgrid, row, col)) {
                return;
            }

            CellRange cellRng = fgrid.GetCellRange(row, col, row, col);
            cellRng.Style = fgrid.Styles[fgstyle.ToString()];
        }

        public void applyStyle(C1FlexGrid fgrid, FGridStyle fgstyle, int row_start, int col_start, int row_end, int col_end)
        {
            if (!IsInRange(fgrid, row_start, col_start) || !IsInRange(fgrid, row_end, col_end)) {
                return;
            }

            CellRange cellRng = fgrid.GetCellRange(row_start, col_start, row_end, col_end);
            cellRng.Style = fgrid.Styles[fgstyle.ToString()];
        }

        private bool IsInRangeOfRow(C1FlexGrid fgrid, int row)
        {
            if (row < fgrid.Rows.Fixed || row >= fgrid.Rows.Count) {
                return false;
            }
            return true;
        }
        #endregion

        #region File
        public void saveAaCSV(C1FlexGrid fgrid, string path)
        {
            using (StreamWriter writer = File.CreateText(path)) {
                int col_count = fgrid.Cols.Count;
                int row_count = fgrid.Rows.Count;

                for (int row = 0; row < row_count; row++) {
                    string line = string.Empty;
                    for (int col = 0; col < col_count; col++) {
                        line += fgrid[row, col] + ",";
                    }
                    writer.WriteLine(line);
                }

                writer.Close();
            }
        }

        #endregion
    }
}
