using System;
using System.Data;
using System.Windows.Forms;
using TResultParser.Lib.Component;
using TResultParser.Lib.ExcelLib;

namespace TResultParser.GUI.Controls {
    public partial class UCXlsList : UserControl {

        #region variables 
        private enum TColumn {
            Index = 0,
            Row, 
            Column,
            SourceData,
            TargetData,
        }

        private FlexgidLib m_FlexGridLib;
  
        public delegate void addLogEvent(string format, params Object[] args);
        private addLogEvent addLog;

        public delegate void setProgressBarEvent(int value);

        private setProgressBarEvent setProgressBarMax;
        private setProgressBarEvent setProgressBarPos;
        #endregion

        #region event 
        public UCXlsList()
        {
            InitializeComponent();
        }

        private void UCXlsList_Load(object sender, EventArgs e)
        {
            m_FlexGridLib = new FlexgidLib();
            init();
        }
        #endregion

        #region Public Functions
        public bool doCompareFiles(XlsCompareItem xlsItem)
        {
            clear();
            if (xlsItem == null || !xlsItem.Valid) {
                return false;
            }

            // Read source file            
            DataTable dtSource = readExcelFile(xlsItem.PathSource, xlsItem.SheetSource);
            if (dtSource == null) {
                addLog("Read Fail!!");
                return false;
            }
            else {
                addLog("col : {0}, row : {1}", dtSource.Columns.Count, dtSource.Rows.Count);
            }

            // Read target file
            DataTable dtTarget = readExcelFile(xlsItem.PathTarget, xlsItem.SheetTarget);
            if (dtTarget == null) {
                addLog("Read Fail!!");
                return false;
            }
            else {
                addLog("col : {0}, row : {1}", dtTarget.Columns.Count, dtTarget.Rows.Count);
            }

            if (dtSource.Columns.Count - dtTarget.Columns.Count > 10) {
                addLog("ERROR!!!(column count)");
                return false;
            }
            
            // compare data
            addLog("Start Compare");
            int col_max = getDataTableSizeMax(dtSource, dtTarget, true);
            int row_max = getDataTableSizeMax(dtSource, dtTarget, false);
            setProgressBarMax(row_max);

            int errorcount = 0;
            for (int row = 0; row < row_max; row++) {
                setProgressBarPos(row+1);
                DataRow rowSource = row < dtSource.Rows.Count  ? dtSource.Rows[row] : null;
                DataRow rowTaget = row < dtTarget.Rows.Count ?  dtTarget.Rows[row]: null;
                if (rowSource == null || rowTaget == null) {
                    errorcount++;
                    string source_data = rowSource == null ? "Null" : (string)rowSource[0];
                    string target_data = rowTaget == null ? "Null" : (string)rowTaget[0];
                    addErrorData(row + 1, 0, source_data, target_data);
                    continue;
                }

                for (int col = 0; col < col_max; col++) {
                    string source_data = col< dtSource.Columns.Count ? (string)rowSource[col] : string.Empty;
                    string target_data = col < dtTarget.Columns.Count ? (string)rowTaget[col] : string.Empty;
                    if (source_data != target_data) {
                        errorcount++;
                        addErrorData(row+1, col+1, source_data, target_data);
                    }
                }
            }

            addLog("Finish : {0}", errorcount);
            return errorcount == 0 ;
        }

        public void setDelegate(addLogEvent addlog, setProgressBarEvent setmax, setProgressBarEvent setpos)
        {
            addLog = addlog;
            setProgressBarMax = setmax;
            setProgressBarPos = setpos;
        }

        public void clear()
        {
            fgridXlsDiff.Rows.Count = 1;
        }
        #endregion

        #region data
        private int getDataTableSizeMax(DataTable dtSource, DataTable dtTarget, bool column)
        {
            if (column) {
                return dtSource.Columns.Count > dtTarget.Columns.Count ? dtSource.Columns.Count : dtTarget.Columns.Count;
            }
            else {
                return dtSource.Rows.Count > dtTarget.Rows.Count ? dtSource.Rows.Count : dtTarget.Rows.Count;
            }
        }
        #endregion

        #region UI
        private void init()
        {
            fgridXlsDiff.Rows.Count = 1;
            fgridXlsDiff.Cols.Count = 4;

            string[] captions = new string[] { "No", "Row", "Column", "Source", "Target" };
            int[] widths = new int[] { 60, 120, 120, 320, 320 };

            m_FlexGridLib.init(fgridXlsDiff, captions, widths);
        }

        private void addErrorData(int row, int col, string source, string target)
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    addErrorData_direct(row, col, source, target);
                }));
            }
            else {
                addErrorData_direct(row, col, source, target);
            }
        }

        private void addErrorData_direct(int row, int col, string source, string target)
        {
            int row_grid = fgridXlsDiff.Rows.Count;
            fgridXlsDiff.Rows.Add();

            fgridXlsDiff[row_grid, (int)TColumn.Index] = row_grid;
            fgridXlsDiff[row_grid, (int)TColumn.Row] = row;
            if (col < 0) {
                fgridXlsDiff[row_grid, (int)TColumn.Column] = "-";
            }
            else {
                fgridXlsDiff[row_grid, (int)TColumn.Column] = col;
                fgridXlsDiff[row_grid, (int)TColumn.SourceData] = source;
                fgridXlsDiff[row_grid, (int)TColumn.TargetData] = target;
            }
        }
        #endregion

        #region excel
        private DataTable readExcelFile(string file_path, int sheetindex)
        {
            addLog("Source File Read : {0}", file_path);
            if (string.IsNullOrEmpty(file_path) || sheetindex <0) {
                return null;
            }

            XlsxManager excel = new XlsxManager();

            if (!excel.open(file_path)) {
                addLog("Create File Error : {0}", file_path);
                return null;
            }

            int col_max = excel.getColumnMaxCount();
            int row_max = excel.getRowMaxCount();
            setProgressBarMax(row_max);

            DataTable dtexcel = new DataTable();
            if (col_max > 0 && row_max > 0) {
                // create column 
                for (int col = 0; col < col_max; col++) {
                    dtexcel.Columns.Add(getColName(col), typeof(string));
                }

                for (int row = 0; row < row_max; row++) {
                    DataRow dtrow = dtexcel.NewRow();
                    for (int col = 0; col < col_max; col++) {
                        dtrow[getColName(col)] = excel.getCellValue(row + 1, col + 1);
                    }
                    dtexcel.Rows.Add(dtrow);
                    setProgressBarPos(row + 1);
                }
            }

            excel.close(false, false);
            return dtexcel;
        }

        private string getColName(int col)
        {
            return string.Format("col_{0}", col);
        }
        #endregion
    }
}
