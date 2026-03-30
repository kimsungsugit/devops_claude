using C1.Win.C1FlexGrid;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using TResultParser.Lib.Component;
using TResultParser.Lib.VectorCAST;
using VectorReporter.Lib.VectorCAST;
using static TResultParser.Lib.Component.FlexgidLib;
using static TResultParser.Lib.Component.XlsxManager;

namespace TResultParser.GUI.Controls {
    public partial class UCVCastMatrics : UserControl {

        #region variable
        #region enum
        private enum UnitColumn {
            No = 0,
            TestID,
            UnitID,
            SubProgram,
            Complexity,
            Statement_Count,
            Statement_Total,
            Statement_Percent,

            Branch_Count,
            Branch_Total,
            Branch_Percent,

            ITSCalled,
            FunctionCalls_Count,
            FunctionCalls_Total,
            FunctionCalls_Percent,
        }

        private enum ITSColumn {
            No = 0,
            Unit,
            UnitID,
            SubProgram,
            Complexity,
            Functions,
            FunctionCalls,
        }
        #endregion

        private FlexgidLib m_FlexGridLib;
        public bool IsITSExecuted { get; set; }

        public bool SearchbarVisible {
            get { return getSearchBarvisible(); }
            set { if (this.Visible) { setSearchBarvisible(value); } }
        }

        public delegate void addLogEvent(string format, params Object[] args);
        private addLogEvent addLogFunc;
        #endregion

        #region event 
        public UCVCastMatrics()
        {
            InitializeComponent();
        }

        private void UCVCastMatrics_Load(object sender, EventArgs e)
        {
            dockVectorCAST.SelectedIndex = 0;
            m_FlexGridLib = new FlexgidLib();
            init();
        }

        private void tboxSearcIT_TextChanged(object sender, EventArgs e)
        {
            fgridITSMatrics.ApplySearch(tboxSearcIT.Text);
        }

        private void tboxSearchUT_TextChanged(object sender, EventArgs e)
        {
            fgridUTSMatrics.ApplySearch(tboxSearchUT.Text);
        }
        #endregion

        #region public 
        public void clear()
        {
            // clear style
            if (fgridUTSMatrics.Rows.Count > 1) {
                CellRange cellRng = fgridUTSMatrics.GetCellRange(1, 1, fgridUTSMatrics.Rows.Count - 1, fgridUTSMatrics.Cols.Count - 1);
                if (cellRng.Style != null) {
                    cellRng.Style = null;
                }
            }

            if (fgridITSMatrics.Rows.Count > 1) {
                CellRange cellRng = fgridITSMatrics.GetCellRange(1, 1, fgridITSMatrics.Rows.Count - 1, fgridITSMatrics.Cols.Count - 1);
                if (cellRng.Style != null) {
                    cellRng.Style = null;
                }
            }

            fgridUTSMatrics.Rows.Count = 1;
            fgridITSMatrics.Rows.Count = 1;
            IsITSExecuted = false;
        }

        public void setDelegate(addLogEvent addlog)
        {
            addLogFunc = addlog;
        }

        public void VCASTMatrics_addData(MatricsType mtype, MatricsManager matricsMag,  UnitBank unitbank, SubFuncManager subFuncs)
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    VCASTRslt_addData_direct(mtype, matricsMag, unitbank, subFuncs);

                }));
            }
            else {
                VCASTRslt_addData_direct(mtype, matricsMag, unitbank, subFuncs);
            }
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

        #region UI 
        private void init()
        {
            string[] caption_ut = new string[] { "No", "TestID", "UnitID", "SubProgram", "Complexity", "Stat(Cnt)", "Stat(TTL)", "Stat(%)", "Branch(Cnt)","Branch(TTL)",
                                                "Branch(%)","ITS Called", "FCalls(Cnt)", "FCalls(TTL)", "FCalls(%)" };
            string[] caption_it = new string[] { "No", "Unit", "UnitID", "SubProgram", "Complexity", "Functions", "Function Calls" };
            int[] width_ut = new int[] { 40, 100, 100, 250, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80 };
            int[] width_it = new int[] { 40, 250, 100, 300, 80, 140, 140 };

            m_FlexGridLib.createStyle(fgridUTSMatrics);
            m_FlexGridLib.init(fgridUTSMatrics, caption_ut, width_ut);

            m_FlexGridLib.createStyle(fgridITSMatrics);
            m_FlexGridLib.init(fgridITSMatrics, caption_it, width_it);

            for (int col = 0; col < caption_ut.Length; col++) {
                bool left = (col >= 1 && col <= 3);
                fgridUTSMatrics.Cols[col].TextAlign = left ? TextAlignEnum.LeftCenter : TextAlignEnum.CenterCenter;
                if (col < fgridITSMatrics.Cols.Count - 1) {
                    fgridITSMatrics.Cols[col].TextAlign = left ? TextAlignEnum.LeftCenter : TextAlignEnum.CenterCenter;
                }
            }

            IsITSExecuted = false;
        }

        private C1FlexGrid getGrid(MatricsType mtype)
        {
            return mtype == MatricsType.Statement ? fgridUTSMatrics : fgridITSMatrics;
        }

        private void VCASTRslt_addData_direct(MatricsType mtype, MatricsManager matricsMag, UnitBank unitbank, SubFuncManager subFuncs)
        {
            C1FlexGrid fgrid = getGrid(mtype);
            Dictionary<string, MatixDataBank> dicbank = matricsMag.getDataBank(mtype);
            if (dicbank == null) {
                return;
            }

            fgrid.Rows.Count = 1;
            MatricStatementItem statement_total = new MatricStatementItem();
            MatricFunCallItem uds_funcall_total = new MatricFunCallItem();
            MatricFunCallItem funcall_total = new MatricFunCallItem();

            foreach (var entry in dicbank) {
                string unit = entry.Key;
                if (entry.Value == null || entry.Value.DicData == null) {
                    continue;
                }


                int row = fgrid.Rows.Count;
                int count = 0;

                // Sort By ID 
                Dictionary<string, IMatrixPrototype> matrixvalues = null;
                if (unitbank.Count >= 0) {
                    foreach (var matric in entry.Value.DicData) {
                        string funname = matric.Value.SubProgram;
                        matric.Value.UnitID = unitbank.getUnitID(funname);
                    }
                    matrixvalues = entry.Value.DicData.OrderBy(item => item.Value.UnitID).ToDictionary(x => x.Key, x => x.Value);
                }
                else {
                    matrixvalues = entry.Value.DicData;
                }

                foreach (var matric in matrixvalues) {
                    bool root = count == 0;
                    fgrid.Rows.Add();
                    fgrid.Rows[row].IsNode = true;
                    fgrid.Rows[row].Node.Level = root ? 0 : 1;

                    fgrid[row, (int)UnitColumn.No] = row;
                    fgrid[row, (int)UnitColumn.TestID] = root ? matric.Value.ID : string.Empty;

                    //Unit Id
                    string funname = matric.Value.SubProgram;
                    fgrid[row, (int)UnitColumn.UnitID] = matric.Value.UnitID;
                    fgrid[row, (int)UnitColumn.SubProgram] = funname;
                    fgrid[row, (int)UnitColumn.Complexity] = matric.Value.Complexity;

                    if (mtype == MatricsType.Statement) {
                        MatricStatementItem item = matric.Value as MatricStatementItem;
                        fgrid[row, (int)UnitColumn.Statement_Count] = item.Statements.Count;
                        fgrid[row, (int)UnitColumn.Statement_Total] = item.Statements.Total;
                        fgrid[row, (int)UnitColumn.Statement_Percent] = item.Statements.Percentage;

                        statement_total.Statements.Count += item.Statements.Count;
                        statement_total.Statements.Total += item.Statements.Total;

                        if (item.Branches != null) {
                            fgrid[row, (int)UnitColumn.Branch_Count] = item.Branches.Count;
                            fgrid[row, (int)UnitColumn.Branch_Total] = item.Branches.Total;
                            fgrid[row, (int)UnitColumn.Branch_Percent] = item.Branches.Percentage;

                            statement_total.Branches.Count += item.Statements.Count;
                            statement_total.Branches.Total += item.Statements.Total;
                        }

                        if (IsITSExecuted) {
                            fgrid[row, (int)UnitColumn.ITSCalled] = item.IsFunction ? "O" : "X";
                            if (item.IsFunction) {
                                if (item.FunctionsCall == null) {
                                    item.FunctionsCall = new CoverageItem();
                                }

                                if (!item.FunctionsCall.Passed) {
 //                                   Debug.Print("{0} : {1}, {2}", item.ID, item.SubProgram, item.FunctionsCall.Coverage);
                                    CoverageItem coverage = subFuncs.getFunctionCallsCoverate(item.SubProgram);
                                    if (coverage != null && coverage.Count > item.FunctionsCall.Count) {
                                        item.FunctionsCall = coverage;
                                    }
                                }

                                fgrid[row, (int)UnitColumn.FunctionCalls_Count] = item.FunctionsCall.Count;
                                fgrid[row, (int)UnitColumn.FunctionCalls_Total] = item.FunctionsCall.Total;
                                fgrid[row, (int)UnitColumn.FunctionCalls_Percent] = item.FunctionsCall.Percentage;

                                uds_funcall_total.FunctionsCall.Count += item.FunctionsCall.Count;
                                uds_funcall_total.FunctionsCall.Total += item.FunctionsCall.Total;
                            }
                        }

                        FGridStyle gridsty = (item.Statements.Count == item.Statements.Total) ? FGridStyle.None : FGridStyle.BgPink;
                        if (!item.IsFunction && IsITSExecuted) {
                            gridsty = gridsty == FGridStyle.None ? FGridStyle.FgRed : FGridStyle.BgPinkFRed;
                        }

                        if (item.IsFunction && item.FunctionsCall != null && item.FunctionsCall.Count != item.FunctionsCall.Total){
                            gridsty = FGridStyle.BgBlueFRed;
                        }

                        if (gridsty != FGridStyle.None) {
                            m_FlexGridLib.applyStyleOnRow(fgrid, gridsty, row);
                        }
                    }
                    else {
                        MatricFunCallItem item = matric.Value as MatricFunCallItem;
                        fgrid[row, (int)ITSColumn.Functions] = item.Functions.Coverage;
                        if (item.FunctionsCall != null) {
                            fgrid[row, (int)ITSColumn.FunctionCalls] = item.FunctionsCall.Coverage;
                        }

                        if (item.Functions.Count == 0) {
                            m_FlexGridLib.applyStyleOnRow(fgrid, FGridStyle.BgPink, row);
                        }

                        funcall_total.Functions.Count += item.Functions.Count;
                        funcall_total.Functions.Total += item.Functions.Total;
                        if (item.FunctionsCall != null) {
                            funcall_total.FunctionsCall.Count += item.FunctionsCall.Count;
                            funcall_total.FunctionsCall.Total += item.FunctionsCall.Total;
                        }
                    }
                    row++;
                    count++;
                }
            }

            // Total Result
            int lastrow = fgrid.Rows.Count;
            fgrid.Rows.Add();
            fgrid[lastrow, 1] = "Total";
            if (mtype == MatricsType.Statement) {
                fgrid[lastrow, (int)UnitColumn.Statement_Count] = statement_total.Statements.Count;
                fgrid[lastrow, (int)UnitColumn.Statement_Total] = statement_total.Statements.Total;
                fgrid[lastrow, (int)UnitColumn.Statement_Percent] = statement_total.Statements.Percentage;
                fgrid[lastrow, (int)UnitColumn.Branch_Count] = statement_total.Branches.Count;
                fgrid[lastrow, (int)UnitColumn.Branch_Total] = statement_total.Branches.Total;
                fgrid[lastrow, (int)UnitColumn.Branch_Percent] = statement_total.Branches.Percentage;

                int functioncount = matricsMag.getFunctionCount();
                int called = matricsMag.getFunctionCalledCount();
                if (functioncount != 0) {
                    fgrid[lastrow, (int)UnitColumn.ITSCalled] = string.Format("{0}/{1}({2} %)", called, functioncount, called * 100 / functioncount);
                    addLog("Function Called: {0}/{1} ({2} %)", called, functioncount, called * 100 / functioncount);
                    fgrid[lastrow, (int)UnitColumn.FunctionCalls_Count] = uds_funcall_total.FunctionsCall.Count;
                    fgrid[lastrow, (int)UnitColumn.FunctionCalls_Total] = uds_funcall_total.FunctionsCall.Total;
                    fgrid[lastrow, (int)UnitColumn.FunctionCalls_Percent] = uds_funcall_total.FunctionsCall.Percentage;
                    addLog("Functions Calling: {0}", uds_funcall_total.FunctionsCall.Coverage);
                }
            }
            else {
                fgrid[lastrow, (int)ITSColumn.Functions] = funcall_total.Functions.Coverage;
                addLog("ITS Coverage : Funtion - {0}", funcall_total.Functions.Coverage);
                if (funcall_total.FunctionsCall != null) {
                    fgrid[lastrow, (int)ITSColumn.FunctionCalls] = funcall_total.FunctionsCall.Coverage;
                    addLog("ITS Coverage : Function Calls- {0}", funcall_total.FunctionsCall.Coverage);
                }
            }

            m_FlexGridLib.applyStyleOnRow(fgrid, FGridStyle.BgLightGray, lastrow);
        }

        private bool getSearchBarvisible()
        {
            return dockVectorCAST.SelectedIndex == 0 ? tboxSearchUT.Visible : tboxSearcIT.Visible;
        }

        private void setSearchBarvisible(bool visible)
        {
            if (visible) {
                if (dockVectorCAST.SelectedIndex == 0) {
                    tboxSearchUT.Visible = true;
                }
                else {
                    tboxSearcIT.Visible = true;
                }
            }
            else {
                if (dockVectorCAST.SelectedIndex == 0) {
                    tboxSearchUT.Visible = false;
                    tboxSearchUT.Text = string.Empty;
                }
                else{
                    tboxSearcIT.Visible = false;
                    tboxSearcIT.Text = string.Empty;
                }
            }
        }

        private void addLog(string format, params Object[] args)
        {
            if (addLogFunc == null) {
                return;
            }

            addLogFunc(format, args);

            string data = args.Count() == 0 ? data = format : string.Format(format, args);
            
            if (string.IsNullOrEmpty(data)) {
                return;
            }

   //         Debug.Print(data + "\r");
        }
        #endregion

        #region file
        private bool saveAsCSV(string filepath)
        {
            string dir = Path.GetDirectoryName(filepath);
            string fname = Path.GetFileNameWithoutExtension(filepath);

            for (int sheet = 1; sheet <= 2; sheet++) {
                C1FlexGrid fgrid = sheet == 1 ? fgridUTSMatrics : fgridITSMatrics;
                string name = sheet == 1 ? "_UT" : "_IT";
                string path = Path.Combine(dir, fname + name + ".csv");

                using (StreamWriter writer = File.CreateText(path)) {
                    int col_count = fgrid.Cols.Count;
                    int row_count = fgrid.Rows.Count;

                    for (int row = 0; row < row_count; row++) {
                        string line = string.Empty;
                        for (int col = 0; col < col_count; col++) {
                            string data = fgrid[row, col] == null ? string.Empty : (string)fgrid[row, col];
                            if (data.IndexOf(",") >= 0) {
                                data = "\"" + data + "\"";
                            }

                            line += (data + ",");
                        }
                        writer.WriteLine(line);
                    }

                    writer.Close();
                }
            }
            System.Diagnostics.Process.Start(filepath);
            return true;
        }

        private bool saveAsExcel(string filepath, bool execute)
        {
            XlsxManager excel = new XlsxManager();
            string dir = Path.GetDirectoryName(filepath);
            string fname = Path.GetFileNameWithoutExtension(filepath);

            int xcol_offset = 1;
            int xrow_offset = 3;
            excel.create(filepath);

            for (int sheet = 1; sheet <= 2; sheet++) {
                C1FlexGrid fgrid = sheet == 1 ? fgridUTSMatrics : fgridITSMatrics;
                string name = sheet == 1 ? "UT Matrics" : "IT Matrics";
                int col_count = fgrid.Cols.Count;
                int row_count = fgrid.Rows.Count;
                excel.selectSheet(sheet, name, true);

                // Title 
                int tblrow = 1;
                excel.writeData(tblrow, 1, name);
                excel.applyStyle(tblrow, 1, tblrow, col_count, XlsCellStyle.Title);

                tblrow = xrow_offset;
                excel.applyStyle(tblrow, 1, tblrow, col_count, XlsCellStyle.Caption);
                excel.applyStyle(tblrow + 1, 1, row_count + xrow_offset - 1, col_count, XlsCellStyle.General);

                // set Col Width 
                for (int col = 0; col < col_count; col++) {
                    excel.setColumnWidth(col + 1, (int)(fgrid.Cols[col].Width * 0.2));
                }

                for (int row = 0; row < row_count; row++) {
                    for (int col = 0; col < col_count; col++) {

                        // Apply style
                        CellRange cellRng = fgrid.GetCellRange(row, col, row, col);
                        if (cellRng.Style != null) {
                            XlsCellStyle xlsstl = m_FlexGridLib.cvrtToExcelStyle(cellRng.Style.Name);
                            if (xlsstl != XlsCellStyle.None) {
                                excel.applyStyle(row + xrow_offset, col + xcol_offset, row + xrow_offset, col + xcol_offset, xlsstl);
                            }
                        }

                        if (fgrid[row, col] == null) {
                            continue;
                        }

                        // write data
                        excel.writeData(row + xrow_offset, col + xcol_offset, fgrid[row, col]);
                        excel.setWrapText(row + xrow_offset, col + xcol_offset, row + xrow_offset, col + xcol_offset, true);
                    }
                }

                // Merged 
                excel.merge(1, 1, 1, 14); // title
                List<CellRange> ranges = m_FlexGridLib.getMergedCellsOnColumns(fgrid);
                foreach (CellRange range in ranges) {
                    excel.merge(range.r1 + xrow_offset, range.c1 + xcol_offset, range.r2 + xrow_offset, range.c2 + xcol_offset);
                }
            }

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
