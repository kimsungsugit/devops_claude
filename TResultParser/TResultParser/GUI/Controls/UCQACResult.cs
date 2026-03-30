using C1.Win.C1FlexGrid;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using TResultParser.Lib.Component;
using TResultParser.Lib.QAC;
using static TResultParser.Lib.Component.FlexgidLib;
using static TResultParser.Lib.Component.XlsxManager;
using static TResultParser.Lib.QAC.HISItem;

namespace TResultParser.GUI.Controls {
    public partial class UCQACResult : UserControl {
        #region variables
        private enum QACColumn {
            Index = 0,
            Function,
            V_G,// STCYC
            LEVEL,// STMIF
            CALLING, // STM29,
            CALLS,//STCAL,
            File,
            Count,
        }

        private FlexgidLib m_FlexGridLib;

        public bool SearchbarVisible {
            get { return tboxSearchQAC.Visible; }
            set { if (this.Visible) { tboxSearchQAC.Visible = value; tboxSearchQAC.Text = string.Empty; } }
        }

        public delegate void addLogEvent(string format, params Object[] args);
        private addLogEvent addLogFunc;
        #endregion

        #region Event 
        public UCQACResult()
        {
            InitializeComponent();
        }

        private void UCQACResult_Load(object sender, EventArgs e)
        {
            m_FlexGridLib = new FlexgidLib();
            init();
        }

        private void tboxSearchQAC_TextChanged(object sender, EventArgs e)
        {
            fgridQAC.ApplySearch(tboxSearchQAC.Text);
        }

        private void fgridQAC_KeyDown(object sender, KeyEventArgs e)
        {
            if ((e.Control && e.KeyCode == Keys.C) || e.KeyCode == Keys.F8) {
                C1FlexGrid fgrid = sender as C1FlexGrid;
                if (fgrid != null) {
                    var ht = fgrid.HitTest();
                    int row = ht.Row;
                    int col = ht.Column;
                    if (!m_FlexGridLib.IsInRange(fgrid, row, col) || row < fgrid.Rows.Fixed || col < fgrid.Cols.Fixed) {
                        return;
                    }

                    if (fgrid[row, col] != null) {
                        string data = (string)fgrid[row, col];
                        Clipboard.SetText(data);
                    }
                }
            }
        }
        #endregion

        #region Public Functions
        public void setDelegate(addLogEvent addlog)
        {
            addLogFunc = addlog;
        }

        public void addQACResult(QACDataManager qacMng)
        {
            foreach (var item in qacMng.ListResult) {
                addItem(item, qacMng);
            }

            addTotalData(qacMng);
        }

        public void clear()
        {
            if (fgridQAC.Rows.Count > 2) {
                CellRange cellRng = fgridQAC.GetCellRange(2, 1, fgridQAC.Rows.Count - 1, fgridQAC.Cols.Count - 1);
                if (cellRng.Style != null) {
                    cellRng.Style = null;
                }
            }

            fgridQAC.Rows.Count = 2;
        }

        public bool save(string filepath, bool execute)
        {
            if (string.IsNullOrEmpty(filepath)) {
                return false;
            }

            if (Path.GetExtension(filepath).ToLower().IndexOf("csv") >= 0) {
                return saveAsCSV(filepath);
            }
            else {
                return saveAsExcel(filepath, execute);
            }
        }
        #endregion

        #region result
        private void addItem(HISItem hisitem, QACDataManager qacMng)
        {
            if (hisitem == null) {
                return;
            }

            MatrixItem[] list = QACDataManager.getMatrixList();
            int row = fgridQAC.Rows.Count;
            int col = 0;
            fgridQAC.Rows.Add();

            fgridQAC[row, col++] = row - 2;
            fgridQAC[row, col++] = hisitem.FunctionName;

            foreach (MatrixItem item in list) {
                col = qacMng.getColumnIndexOfMatrixItem(item);
                if (col < 1) {
                    continue;
                }
                string value = hisitem.getMatricValue(item);
                int warninglevel = qacMng.checkWarningLevel(item, value);
                qacMng.updateSpecOverCount(item, warninglevel);

                if (warninglevel > 0) {
                    addLog("[{0}] {1} , {2} ,  {3} => {4}", row, hisitem.FunctionName, item, value, warninglevel);
                }

                fgridQAC[row, col] = value;
                QAC_applyStyle(false, row, col, warninglevel);
            }
            col++;
            fgridQAC[row, col] = hisitem.FileName;
        }

        private void addTotalData(QACDataManager qacMng)
        {
            MatrixItem[] list = QACDataManager.getMatrixList();

            for (int wlevel = 0; wlevel <= 3; wlevel++) {
                int row = fgridQAC.Rows.Count;
                int col = 0;
                fgridQAC.Rows.Add();
                fgridQAC[row, col++] = "Total";
                QAC_applyStyle(true, row, col, 0);
                fgridQAC[row, col++] = string.Format("Level {0}", wlevel);

                string specstring = string.Empty;
                foreach (MatrixItem item in list) {
                    col = qacMng.getColumnIndexOfMatrixItem(item);
                    if (col < 1 || !qacMng.DicSpecOverCount.ContainsKey(item) || wlevel >= qacMng.DicSpecOverCount[item].SpecCount) {
                        fgridQAC[row, col] = "-";
                        m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgLightGray, row, col);
                        continue;
                    }

                    int count = qacMng.DicSpecOverCount[item].ListSpec[wlevel];
                    fgridQAC[row, col] = count.ToString();
                    QAC_applyStyle(true, row, col, wlevel);

                    if (!string.IsNullOrEmpty(specstring)) {
                        specstring += ", ";
                    }
                    specstring += qacMng.getSpecString(item, wlevel);
                }
                // Add Spec 
                fgridQAC[row, (int)QACColumn.File] = specstring;
                m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgLightGray, row, (int)QACColumn.File);
            }
        }
        #endregion

        #region Ui 
        private void QAC_applyStyle(bool total, int row, int col, int warninglevel)
        {
            if (row < 2 || col < 1 || warninglevel == 0) {
                if (total) {
                    m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgLightGray, row, col);
                }
                return;
            }

            switch (warninglevel) {
                case 1:
                    m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgYellow, row, col); //warning Level1
                    break;
                case 2:
                    m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgOrange, row, col);//warning Level2
                    break;
                case 3:
                    m_FlexGridLib.applyStyle(fgridQAC, FGridStyle.BgRed, row, col);//warning Level3
                    break;
            }
        }

        private void init()
        {
            tboxSearchQAC.Visible = false;
            fgridQAC.Rows.Fixed = 2;

            fgridQAC.Rows.Count = 2;
            fgridQAC.Cols.Count = (int)QACColumn.Count;

            int row = 0;
            int col = 0;
            fgridQAC[row, col] = "Index";
            fgridQAC[row + 1, col] = "Index";
            fgridQAC.Cols[col].AllowMerging = true;
            fgridQAC.Cols[col].Width = 80;
            fgridQAC.Cols[col++].TextAlign = TextAlignEnum.CenterCenter;

            fgridQAC[row, col] = "Function";
            fgridQAC[row + 1, col] = "Function";
            fgridQAC.Cols[col].AllowMerging = true;
            fgridQAC.Cols[col++].Width = 300;

            MatrixItem[] list = QACDataManager.getMatrixList();
            foreach (MatrixItem item in list) {
                fgridQAC[row, col] = getTitle(item, true);
                fgridQAC[row + 1, col] = getTitle(item, false);
                fgridQAC.Cols[col].Width = 80;
                fgridQAC.Cols[col].TextAlign = TextAlignEnum.CenterCenter;
                col++;
            }

            fgridQAC[row, col] = "File";
            fgridQAC[row + 1, col] = "File";
            fgridQAC.Cols[col].AllowMerging = true;
            fgridQAC.Cols[col].Width = 500;

            m_FlexGridLib.createStyle(fgridQAC);
        }


        private void addLog(string format, params Object[] args)
        {
            if (addLogFunc == null) {
                return;
            }

            addLogFunc(format, args);

            string data = string.Empty;
            if (args.Count() == 0) {
                data = format;
            }
            else {
                data = string.Format(format, args);
            }

            if (string.IsNullOrEmpty(data)) {
                return;
            }

            data += "\r";
            Debug.Print(data);
        }
        #endregion

        #region file
        private bool saveAsCSV(string filepath)
        {
            int col_count = fgridQAC.Cols.Count;
            int row_count = fgridQAC.Rows.Count;

            using (StreamWriter writer = File.CreateText(filepath)) {
                for (int row = 0; row < row_count; row++) {
                    string line = string.Empty;
                    for (int col = 0; col < col_count; col++) {
                        string data = fgridQAC[row, col] == null ? string.Empty : (string)fgridQAC[row, col];
                        if (data.IndexOf(",") >= 0) {
                            data = "\'" + data + "\'";
                        }

                        line += (data + ",");
                    }
                    writer.WriteLine(line);
                }

                writer.Close();
            }

            System.Diagnostics.Process.Start(filepath);
            return true;
        }

        private bool saveAsExcel(string filepath, bool execute)
        {
            XlsxManager excel = new XlsxManager();
            int col_count = fgridQAC.Cols.Count;
            int row_count = fgridQAC.Rows.Count;

            int xcol_offset = 1;
            int xrow_offset = 3;
            int title_col_count = 7;

            string title = "QAC Report";
            excel.create(filepath);
            excel.selectSheet(1, title, true);

            // Excel Format
            // Title 
            int tblrow = 1;
            excel.writeData(tblrow, 1, title);
            excel.applyStyle(tblrow, 1, tblrow, title_col_count, XlsCellStyle.Title);

            tblrow = xrow_offset;
            excel.applyStyle(tblrow, 1, tblrow + 2, col_count, XlsCellStyle.Caption);
            excel.applyStyle(tblrow + 2, 1, row_count + xrow_offset - 1, col_count, XlsCellStyle.General);

            // set Col Width 
            for (int col = 0; col < col_count; col++) {
                excel.setColumnWidth(col + 1, (int)(fgridQAC.Cols[col].Width * 0.2));
            }

            for (int row = 0; row < row_count; row++) {
                for (int col = 0; col < col_count; col++) {
                    // Apply style
                    CellRange cellRng = fgridQAC.GetCellRange(row, col, row, col);
                    if (cellRng.Style != null) {
                        XlsCellStyle xlsstl = m_FlexGridLib.cvrtToExcelStyle(cellRng.Style.Name);
                        if (xlsstl != XlsCellStyle.None) {
                            excel.applyStyle(row + xrow_offset, col + xcol_offset, row + xrow_offset, col + xcol_offset, xlsstl);
                        }
                    }

                    if (fgridQAC[row, col] == null) {
                        continue;
                    }

                    // write data
                    excel.writeData(row + xrow_offset, col + xcol_offset, fgridQAC[row, col]);
                }
            }

            // Merged 
            excel.merge(1, 1, 1, title_col_count); // title
            List<CellRange> ranges = m_FlexGridLib.getMergedCellsOnColumns(fgridQAC);
            foreach (CellRange range in ranges) {
                excel.merge(range.r1 + xrow_offset, range.c1 + xcol_offset, range.r2 + xrow_offset, range.c2 + xcol_offset);
            }

            // Excel Close
            excel.close(true);
            Thread.Sleep(1000);
            if (execute) {
                excel.execute(filepath);
            }
            return true;
        }
        #endregion
    }
}
