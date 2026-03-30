using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using TResultParser.Lib.Component;
using TResultParser.Lib.ExcelLib;
using TResultParser.Lib.QAC;
using TResultParser.Lib.VectorCAST;
using VectorReporter.Lib.VectorCAST;
using static TResultParser.GUI.Controls.UCDataType;
using static TResultParser.Lib.VectorCAST.TCBank;

namespace TResultParser {
    public partial class FormMain : Form {

        #region Variables
        private DataMode m_DataMode;
        private bool m_UserBreak;

        // QAC 
        private QACDataManager m_QACMng;

        // VCAST TC 
        private VCastItemMode m_VCMode;
        private bool m_boVCUnitMode;
        private TCManager m_TCManager;

        // VCAST Matrics 
        private string m_UnitPath;
        private UnitBank m_UnitBank;
        private MatricsManager m_MatricsManager;
        private SubFuncManager m_SubFuncManager;

        private bool m_doUTRLoad;
        private bool m_doITRLoad;
        private string m_UTResultPath;
        private string m_ITResultPath;
        private string m_ItAggrPath;

        // VAST 
        private const VCASTVersion VCAST_VERSION_2025 = VCASTVersion.Ver2025;
        private VCASTVersion m_VcastVer;

        // Excel Compare
        private XlsCompareItem m_XlsCompare;

        // Thread Process
        private Thread m_thLoadProc = null;

        // Report 
        private Thread m_thMakingReport = null;
        private string m_ReportPath;

        // inti file 
        private IniFile m_IniFile;

        // Timer
        private int m_StartTick;

        // public 
        private bool ConsolMode = false;
        private List<string> Arguments = new List<string>();

        #endregion

        #region event 
        public FormMain()
        {
            InitializeComponent();
        }

        // grammer : 
        // old version : tresultparser q report_directory
        // new version : tresultparser qn report_directory
        public FormMain(string[] args)
        {
            InitializeComponent();

            if (args.Length == 2) {
                ConsolMode = true;
            }
            Arguments = args.ToList();
        }

        private void FormMain_Load(object sender, EventArgs e)
        {
            Version oVersion = new Version(System.Windows.Forms.Application.ProductVersion);
            string version = oVersion.ToString();
            labelVersion.Text = string.Format("  Ver.{0}  ", version);

            m_QACMng = new QACDataManager();
            m_TCManager = new TCManager();
            m_UnitBank = new UnitBank();
            m_MatricsManager = new MatricsManager();
            m_SubFuncManager = new SubFuncManager();

            m_XlsCompare = new XlsCompareItem();
            m_IniFile = new IniFile();

            init();

            if (ConsolMode) {
                exeConsolmode();
                Environment.Exit(0);
            }
        }

        private void FormMain_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.Control && e.KeyCode == Keys.F || e.KeyCode == Keys.F7) {
                if (m_DataMode == DataMode.QAC_Result) {
                    ucQACResult.SearchbarVisible = true;
                }

                if (m_DataMode == DataMode.VC_TestCase) {
                    ucVCTCList.SearchbarVisible = true;
                }

                if (m_DataMode == DataMode.VC_Matrics) {
                    ucVCMatrics.SearchbarVisible = true;
                }
            }

            if (e.KeyCode == Keys.Escape) {
                ucQACResult.SearchbarVisible = false;
                ucVCTCList.SearchbarVisible = false;
                ucVCMatrics.SearchbarVisible = false;
            }
        }

        //-------------------------------------------------------------------------------------------------
        // QAC
        //-------------------------------------------------------------------------------------------------
        #region QAC
        private void btnQACLoad_Click(object sender, EventArgs e)
        {
            QACLoadProc();
        }

        private void QACLoadProc()
        {
            ucQACResult.clear();
            bool oldversion = chkQACOldversion.Checked;

            string path = tboxQACFilePath.Text;
            addLog("QAC Read : {0}", path);
            bool status = m_QACMng.readFile(oldversion, path);
            if (!status) {
                addLog("QAC Read File Fail!!");
                return;
            }

            m_IniFile.setIntValue(IniFile.SECTION_GLOBAL, IniFile.GLB_DATAMODE, (int)m_DataMode);
            m_IniFile.setStringValue(IniFile.SECTION_QAC, IniFile.QAC_PATH, path);
            m_IniFile.setBoolValue(IniFile.SECTION_QAC, IniFile.QAC_OLDVERSION, oldversion);
            m_IniFile.save();

            ucQACResult.addQACResult(m_QACMng);

            addLog("QAC Read File OK!!");
        }


        private void btnQACReport_Click(object sender, EventArgs e)
        {
            m_ReportPath = showSaveDlg();
            if (string.IsNullOrEmpty(m_ReportPath)) {
                addLog("File name is empty!!");
                return;
            }

            // start Script process 
            m_thMakingReport = new Thread(makingReportProc);
            m_thMakingReport.Start();
        }

        private void btnQACPath_Click(object sender, EventArgs e)
        {
            DlgOpenFile(tboxQACFilePath, "HTML files (*.html)|*.html|All files (*.*)|*.*");
        }
        #endregion

        //-------------------------------------------------------------------------------------------------
        // VectorCAST Test Case
        //-------------------------------------------------------------------------------------------------
        #region Test Case
        private void btnVCTCPath_Click(object sender, EventArgs e)
        {
            DlgFolder(tboxVCTCPath);
        }

        private void btnVCRsltPath_Click(object sender, EventArgs e)
        {
            DlgFolder(tboxVCRsltPath);
        }

        private void btnVCTCLoad_Click(object sender, EventArgs e)
        {
            int index = cmbVCMode.SelectedIndex;
            if (index < 0) {
                addLog("VC Mode Error!!");
                return;
            }

            m_VCMode = (VCastItemMode)index;
            m_boVCUnitMode = chkVCTCUTSMode.Checked;
            m_TCManager.clear();
            ucVCTCList.clear();
            ucVCTCList.IsActualDataOnly = chkVCTCDataOnly.Checked;
            m_VcastVer = VCAST_VERSION_2025;//            (VCASTVersion)cmbVCASTVersion.SelectedIndex;

            m_UserBreak = false;

            string path = tboxVCTCPath.Text;
            if (string.IsNullOrEmpty(path) || !Directory.Exists(path)) {
                addLog("Directory not exists!!");
                return ;
            }

            startTimer();
            // Ini file 
            m_IniFile.setIntValue(IniFile.SECTION_GLOBAL, IniFile.GLB_DATAMODE, (int)m_DataMode);
            m_IniFile.setIntValue(IniFile.SECTION_VCAST_COMMON, IniFile.VCAST_VCASTVER, (int)m_VcastVer);

            m_IniFile.setStringValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_TCPATH, tboxVCTCPath.Text);
            m_IniFile.setStringValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_RSLTPATH, tboxVCRsltPath.Text);
            m_IniFile.setBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_UNIT, m_boVCUnitMode);
            m_IniFile.setBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_ACTONLY, chkVCTCDataOnly.Checked);
            m_IniFile.setBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_AUTOSIZE, chkVCTCAutoSize.Checked);
            
            m_IniFile.save();

            setComponentEnabled(false);
            // start Script process 
            m_thLoadProc = new Thread(VCASTTC_loadProc);
            m_thLoadProc.Start();
        }

        private void btnVCTCReport_Click(object sender, EventArgs e)
        {
            m_ReportPath = showSaveDlg();
            if (string.IsNullOrEmpty(m_ReportPath)) {
                addLog("File name is empty!!");
                return;
            }

            addLog("Start making report...");
            // start Script process 
            m_thMakingReport = new Thread(makingReportProc);
            m_thMakingReport.Start();
        }

        private void btnVCTCBreak_Click(object sender, EventArgs e)
        {
            m_UserBreak = true;
        }

        private void chkVCTCAutoSize_CheckedChanged(object sender, EventArgs e)
        {
            ucVCTCList.AutoColSize = chkVCTCAutoSize.Checked;
        }

        private void cmbVCMode_SelectedIndexChanged(object sender, EventArgs e)
        {
            VCastItemMode vcMode = (VCastItemMode)cmbVCMode.SelectedIndex;

            chkVCTCDataOnly.Enabled = vcMode >= VCastItemMode.TestResult;

            labelVCTCPath.Visible = vcMode != VCastItemMode.TestResult;
            tboxVCTCPath.Visible = vcMode != VCastItemMode.TestResult;
            btnVCTCPath.Visible = vcMode != VCastItemMode.TestResult;

            labelVCRsltPath.Visible = vcMode != VCastItemMode.TestCase;
            tboxVCRsltPath.Visible = vcMode != VCastItemMode.TestCase;
            btnVCRsltPath.Visible = vcMode != VCastItemMode.TestCase;

        }
        #endregion

        //-------------------------------------------------------------------------------------------------
        // VectorCAST Matrics
        //-------------------------------------------------------------------------------------------------
        #region VCast Matrics
        private void btnVCRsltLoad_Click(object sender, EventArgs e)
        {
            setComponentEnabled(false);
            m_UnitBank.clear();

            m_UnitPath = tboxVCRsltUnitList.Text;
            m_doUTRLoad = chkVCUTRLoad.Checked;
            m_doITRLoad = chkIVCTRLoad.Checked;
            m_UTResultPath = tboxVCUTRPath.Text;
            m_ITResultPath = tboxVCITRPath.Text;
            m_ItAggrPath = tboxVCITAggPath.Text;
            m_VcastVer = VCAST_VERSION_2025;
  //          m_VcastVer = (VCASTVersion)cmbVCASTVersion.SelectedIndex;

            VCASTMatrics_clear();

            if ((m_doUTRLoad && !Directory.Exists(m_UTResultPath)) || (m_doITRLoad && !Directory.Exists(m_ITResultPath))) {
                addLog("Directory not exists!! ({0})", m_UTResultPath);
                return;
            }

            // Save INI 
            m_IniFile.setIntValue(IniFile.SECTION_GLOBAL, IniFile.GLB_DATAMODE, (int)m_DataMode);
            m_IniFile.setIntValue(IniFile.SECTION_VCAST_COMMON, IniFile.VCAST_VCASTVER, (int)m_VcastVer);

            m_IniFile.setStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNITID, tboxVCRsltUnitList.Text);
            m_IniFile.setBoolValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNIT, chkVCUTRLoad.Checked);
            m_IniFile.setStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNITPATH, tboxVCUTRPath.Text);
            m_IniFile.setBoolValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_IT, chkIVCTRLoad.Checked);
            m_IniFile.setStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_ITPATH, tboxVCITRPath.Text);
            m_IniFile.setStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_ITAGGPATH, tboxVCITAggPath.Text);

            m_IniFile.save();

            // start Script process 
            m_thLoadProc = new Thread(VCASTMatrics_loadSpecProc);
            m_thLoadProc.Start();
        }

        private void btnVCRsltReport_Click(object sender, EventArgs e)
        {
            m_ReportPath = showSaveDlg();
            if (string.IsNullOrEmpty(m_ReportPath)) {
                addLog("File name is empty!!");
                return;
            }

            // start Script process 
            m_thMakingReport = new Thread(makingReportProc);
            m_thMakingReport.Start();
        }

        private void btnVCASTUnitID_Click(object sender, EventArgs e)
        {
            DlgOpenFile(tboxVCRsltUnitList, "csv files (*.csv)|*.csv|All files (*.*)|*.*");
        }

        private void btnUTMatrixPath_Click(object sender, EventArgs e)
        {
            DlgFolder(tboxVCUTRPath);
        }

        private void btnITSResultPath_Click(object sender, EventArgs e)
        {
            DlgFolder(tboxVCITRPath);
        }
        private void btnVCITAggPath_Click(object sender, EventArgs e)
        {
            DlgFolder(tboxVCITAggPath);
        }
        #endregion

        //-------------------------------------------------------------------------------------------------
        // Excel 
        //-------------------------------------------------------------------------------------------------
        #region Excel 
        private void btnXlsPathSource_Click(object sender, EventArgs e)
        {
            DlgOpenFile(tboxXlsPathSource, "Excel files (*.xlsx)|*.xlsx");
        }

        private void btnXlsPathTarget_Click(object sender, EventArgs e)
        {
            DlgOpenFile(tboxXlsPathTarget, "Excel files (*.xlsx)|*.xlsx");
        }

        private void btnXlsCompare_Click(object sender, EventArgs e)
        {
            m_XlsCompare = new XlsCompareItem(tboxXlsPathSource.Text, tboxXlsPathTarget.Text,
                                getIntFromTbox(tboxXlsSheetSource), getIntFromTbox(tboxXlsSheetTarget));

            addLog("Excel Compare Start!!");
            if (!m_XlsCompare.Valid) {
                addLog("Excel Parameter Error!!");
                return;
            }

            // Save INI 
            m_IniFile.setIntValue(IniFile.SECTION_GLOBAL, IniFile.GLB_DATAMODE, (int)m_DataMode);
            m_IniFile.setStringValue(IniFile.SECTION_EXCEL, IniFile.XLS_SOURCEPATH, m_XlsCompare.PathSource);
            m_IniFile.setIntValue(IniFile.SECTION_EXCEL, IniFile.XLS_SOURCESHEET, m_XlsCompare.SheetSource);
            m_IniFile.setStringValue(IniFile.SECTION_EXCEL, IniFile.VCAST_TC_RSLTPATH, m_XlsCompare.PathTarget);
            m_IniFile.setIntValue(IniFile.SECTION_EXCEL, IniFile.VCAST_TC_ACTONLY, m_XlsCompare.SheetTarget);
            m_IniFile.save();

            m_thLoadProc = new Thread(compareExcelFiles);
            m_thLoadProc.Start();
        }
        #endregion
        #endregion

        #region Data Mode
        private void DataMode_init()
        {
            m_DataMode = (DataMode)m_IniFile.getIntValue(IniFile.SECTION_GLOBAL, IniFile.GLB_DATAMODE, (int)DataMode.QAC_Result);
            setDataMode(m_DataMode);

            dockResult.ShowTabs = false;

            ucDataType.selectDataMode(m_DataMode);
            ucDataType.setDelegate(setDataMode);
        }

        private void setDataMode(DataMode datamode)
        {
            m_DataMode = datamode;

            switch (m_DataMode) {
                case DataMode.QAC_Result:
                    dockResult.SelectedIndex = 0;
                    break;
                case DataMode.VC_TestCase:
                    dockResult.SelectedIndex = 1;
                    break;
                case DataMode.VC_Matrics:
                    dockResult.SelectedIndex = 2;
                    break;
                case DataMode.Xls_Compare: 
                    dockResult.SelectedIndex = 3;
                    break;
                }

            SetVisibleVC();
            setCaption(m_DataMode);
        }

        private void SetVisibleVC()
        {
            if (m_DataMode == DataMode.QAC_Result || m_DataMode == DataMode.Xls_Compare) {
                return;
            }

            bool visible_agg = m_DataMode == DataMode.VC_Matrics;
            tboxVCITAggPath.Visible = visible_agg;
            btnVCITAggPath.Visible = visible_agg;
        }

        #endregion

        #region QAC
        private void QAC_init()
        {
            tboxQACFilePath.Text = m_IniFile.getStringValue(IniFile.SECTION_QAC, IniFile.QAC_PATH, string.Empty);
            chkQACOldversion.Checked = m_IniFile.getBoolValue(IniFile.SECTION_QAC, IniFile.QAC_OLDVERSION, false);
        }
        #endregion

        #region proc
        // QAC Report 중 "_HMR_"이 이름에 들어간 파일의 최신본을 읽어서 
        // QAC 분석을 진행하고 동일한 이름으로 확장자명만 바꿔서 엑셀 레포트 생성 
        private string getQACREportPath(string directory)
        {
            if (string.IsNullOrEmpty(directory) || !Directory.Exists(directory)) {
                return string.Empty;
            }

            try {
                var files = Directory.GetFiles(directory, "*_HMR_*.html");

                var latestFile = files
                    .Select(f => new FileInfo(f))
                    .OrderByDescending(f => f.CreationTime)
                    .FirstOrDefault();

                if (latestFile == null) {
                    Debug.Print("File not exists!!");
                }
                else {
                    Debug.Print("File : {0}", latestFile.FullName);
                    return latestFile.FullName;
                }
            }
            catch (Exception ex) {
                Debug.Print("Error : {0}", ex.Message);
            }

            return string.Empty;
        }

        private bool exeConsolmode()
        {
            if (!ConsolMode) {
                return true;
            }

            string cmd = Arguments[0].ToLower();
            string path = getQACREportPath(Arguments[1]) ;
            if ((cmd == "q" || cmd == "qn" ) && File.Exists(path)){
                if (cmd == "qn") {
                    addLog("QAC Mode : Helix QAC ");
                    chkQACOldversion.Checked = false;
                }
                else {
                    addLog("QAC Mode : PRQA ");
                    chkQACOldversion.Checked = true;
                }

                setDataMode(DataMode.QAC_Result);
                tboxQACFilePath.Text = path;
                Thread.Sleep(1000);
                btnQACLoad_Click(null, null);

                // Report 
                m_ReportPath = Path.ChangeExtension(path, ".xlsx");
                addLog("Result File  : {0}", m_ReportPath);
                makingReport();
            }
            else {
                addLog("Wrong Parameter!!");
            }

            return true;
        }

        private void endProc()
        {
            stopTimer();
            setComponentEnabled(true);
        }
        #endregion

        #region [VectorCAST]Test Case
        private void VCASTTC_loadProc()
        {
            // Read Files 
            if (m_VCMode == VCastItemMode.TestCase || m_VCMode == VCastItemMode.TestReport) {
                string path_tc = getTextFromTbox(tboxVCTCPath);
                if (!VCAST_readfiles(path_tc, true)) {
                    stopTimer();
                    return;
                }
            }

            if (m_VCMode == VCastItemMode.TestResult || m_VCMode == VCastItemMode.TestReport) {
                string path_result = getTextFromTbox(tboxVCRsltPath);
                if (!VCAST_readfiles(path_result, false)) {
                    stopTimer();
                    return;
                }
            }

            m_TCManager.sortByTCID();

            int index = 0;
            setProgressBarPos(index);
            ucVCTCList.setColumnCount(m_TCManager.MaxInputCount, m_TCManager.MaxExpResultCount, m_TCManager.MaxActResultCount, m_VCMode, m_boVCUnitMode);
            
            int passed_count = 0;
            int total_count = 0;
            int tc_index = 0;

            if (m_VCMode == VCastItemMode.TestResult) {
                foreach (var item in m_TCManager.ListActResult) {
                    if (m_UserBreak) {
                        break;
                    }

                    total_count += item.TestCount;
                    passed_count += item.PassedCount;

                    ucVCTCList.addTCData(null, item, ref tc_index);
                    setProgressBarPos(++index);
                }

                ucVCTCList.addTotalResult(total_count, passed_count);
            }
            else {
                foreach (var item in m_TCManager.ListTestCase) {
                    if (m_UserBreak) {
                        break;
                    }

                    total_count += item.TestCount;
                    TCBank asltdata = m_VCMode == VCastItemMode.TestCase ? null : m_TCManager.getActualData(item.Envirnment);
                    if (asltdata != null) {
                        passed_count += asltdata.PassedCount;
                    }
                    ucVCTCList.addTCData(item, asltdata, ref tc_index);
                    setProgressBarPos(++index);
                }

                ucVCTCList.addTotalResult(total_count, passed_count);
            }

            setProgressBarPos(-1);
            ucVCTCList.setTextAlign();

            if (m_UserBreak) {
                addLog("User Stopped!!");
            }
            else {
                addLog("Finish!!!");
            }
            stopTimer();
        }

        private bool VCAST_readfiles(string path, bool file_tc)
        {
            if (!Directory.Exists(path)) {
                addLog("Directory not exists!!");
                return false;
            }

            IEnumerable<string> listfile = Directory.EnumerateFiles(path, "*.html");
            setProgressBarMax(listfile.Count());

            int index = 0;
            addLog("Read Files ......");
            foreach (string filepath in listfile) {
                if (m_UserBreak) {
                    return false;
                }
                string filename = Path.GetFileName(filepath);
                TCBank tcbank = new TCBank(m_VcastVer, filepath, m_VCMode, file_tc, m_boVCUnitMode);
                if (!tcbank.IsValid) {
                    addLog("{0} : read fail!!", filename);
                    return false;
                }

                addLog("[{0}] {1}, Result = {2}", index++, filename, tcbank.IsValid);
                m_TCManager.addItem(tcbank);
                setProgressBarPos(++index);
            }

            return true;
        }

        private void VCAST_init()
        {
            m_VCMode = (VCastItemMode)m_IniFile.getIntValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_TYPE, (int)VCastItemMode.TestCase);
            cmbVCMode.SelectedIndex = (int)m_VCMode;
            m_VcastVer = VCAST_VERSION_2025;
//            (VCASTVersion)m_IniFile.getIntValue(IniFile.SECTION_VCAST_COMMON, IniFile.VCAST_VCASTVER, (int)VCASTVersion.Ver2025);

  //          cmbVCASTVersion.SelectedIndex = (int)m_VcastVer;
            tboxVCTCPath.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_TCPATH, string.Empty);
            tboxVCRsltPath.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_RSLTPATH, string.Empty);
            chkVCTCUTSMode.Checked = m_IniFile.getBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_UNIT, true);
            chkVCTCDataOnly.Checked = m_IniFile.getBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_ACTONLY, false);
            chkVCTCAutoSize.Checked = m_IniFile.getBoolValue(IniFile.SECTION_VCAST_TC, IniFile.VCAST_TC_AUTOSIZE, false);

            ucVCTCList.setDelegate(addLog);
        }
        #endregion

        #region [VectorCAST] Matrics
        public void VCASTMatrics_loadSpecProc()
        {
            m_UnitBank.loadUnitData(m_UnitPath);
            loadITSAggCoverageReport();

            // Read
            for (MatricsType mtype = MatricsType.Statement; mtype <= MatricsType.Functions; mtype++) {
                bool execute = mtype == MatricsType.Statement ? m_doUTRLoad : m_doITRLoad;
                if (!execute) {
                    continue;
                }

                string path = mtype == MatricsType.Statement ? m_UTResultPath : m_ITResultPath;
                if (string.IsNullOrEmpty(path) || !Directory.Exists(path)) {
                    continue;
                }

                // Load Unit Test 
                var filelist = Directory.EnumerateFiles(path, "*.*", SearchOption.TopDirectoryOnly).Where(s => s.EndsWith(".html"));
                if (filelist == null || filelist.Count() == 0) {
                    addLog("Can not get file list");
                    return;
                }

                if (mtype == MatricsType.Functions) {
                    ucVCMatrics.IsITSExecuted = true;
                }
                setProgressBarMax(filelist.Count());

                int filecount = 0;
                foreach (string filepath in filelist) {
                    string filename = Path.GetFileName(filepath);
                    bool status = m_MatricsManager.readFile(m_VcastVer, mtype, filepath);
                    if (!status) {
                        return;
                    }

                    filecount++;
                    setProgress(filecount);

                    addLog("[{0}] {1} : {2}", filecount++, filename, status);
                }
            }

            // Result 
            for (MatricsType mtype = MatricsType.Statement; mtype <= MatricsType.Functions; mtype++) {
                bool execute = mtype == MatricsType.Statement ? m_doUTRLoad : m_doITRLoad;
                if (!execute) {
                    continue;
                }

                ucVCMatrics.VCASTMatrics_addData(mtype, m_MatricsManager, m_UnitBank, m_SubFuncManager );
            }

            setComponentEnabled(true);
            addLog("Finish!!");
        }

        private void VCASTMatrics_clear()
        {
            m_MatricsManager.clear();
            m_SubFuncManager.clear();
            tboxLog.Text = string.Empty;

            ucVCMatrics.clear();
        }

        private void VCASTMatrics_init()
        {
            tboxVCRsltUnitList.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNITID, string.Empty);
            chkVCUTRLoad.Checked = m_IniFile.getBoolValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNIT, true);
            tboxVCUTRPath.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_UNITPATH, string.Empty);
            chkIVCTRLoad.Checked = m_IniFile.getBoolValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_IT, true);
            tboxVCITRPath.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_ITPATH, string.Empty);
            tboxVCITAggPath.Text = m_IniFile.getStringValue(IniFile.SECTION_VCAST_MT, IniFile.VCAST_MT_ITAGGPATH, string.Empty);

            m_UnitPath = string.Empty;
            m_doUTRLoad = false;
            m_doITRLoad = false;
            m_UTResultPath = string.Empty;
            m_ITResultPath = string.Empty;
            m_ItAggrPath = string.Empty;

            ucVCMatrics.IsITSExecuted = false;
            ucVCMatrics.setDelegate(addLog);
        }

        private bool loadITSAggCoverageReport()
        {
            if (m_boVCUnitMode) {
                return true;
            }

            if (string.IsNullOrEmpty(m_ItAggrPath) || !Directory.Exists(m_ItAggrPath)) {
                return false;
            }

            var filelist = Directory.EnumerateFiles(m_ItAggrPath, "*.*", SearchOption.TopDirectoryOnly).Where(s => s.EndsWith(".html"));
            foreach (string path in filelist) {
                bool status = m_SubFuncManager.loadITSAggate(m_VcastVer, path);
        //        Debug.Print("{0} : {1}", Path.GetFileName(path), status);
            }
            return true;
        }
        #endregion

        #region excel 
        private void compareExcelFiles()
        {
            setComponentEnabled(false);
            bool status = ucExcelList.doCompareFiles(m_XlsCompare);
            setComponentEnabled(true);
            if (status) {
                addLog("Same File!!");
            }
            else {
                addLog("Some data not match!!");
            }
        }

        private void Xls_clear()
        {
            m_XlsCompare.clear();
        }

        private void Xls_init()
        {
            tboxXlsPathSource.Text = m_IniFile.getStringValue(IniFile.SECTION_EXCEL, IniFile.XLS_SOURCEPATH, string.Empty);
            tboxXlsSheetSource.Text = m_IniFile.getStringValue(IniFile.SECTION_EXCEL, IniFile.XLS_SOURCESHEET, "1");

            tboxXlsPathTarget.Text = m_IniFile.getStringValue(IniFile.SECTION_EXCEL, IniFile.VCAST_TC_RSLTPATH, string.Empty);
            tboxXlsSheetTarget.Text = m_IniFile.getStringValue(IniFile.SECTION_EXCEL, IniFile.VCAST_TC_ACTONLY, "1");

            ucExcelList.setDelegate(addLog, setProgressBarMax, setProgressBarPos);
        }
        #endregion

        #region UI
        private void init()
        {
            m_IniFile.open();

            this.KeyPreview = true;
            DataMode_init();

            // QAC 
            QAC_init();

            // TC 
            VCAST_init();
            VCASTMatrics_init();

            // Xls 
            Xls_init();

            tboxLog.Clear();
        }

        private void setComponentEnabled(bool boEnabled)
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    setComponentEnabled_Direct(boEnabled);
                }));
            }
            else {
                setComponentEnabled_Direct(boEnabled);
            }
        }

        private void setComponentEnabled_Direct(bool boEnabled)
        {
            // QAC
            tboxQACFilePath.Enabled = boEnabled;
            btnQACPath.Enabled = boEnabled;
            btnQACLoad.Enabled = boEnabled;
            btnQACReport.Enabled = boEnabled;

            // VCAST TestCase
            tboxVCTCPath.Enabled = boEnabled;
            btnVCTCPath.Enabled = boEnabled;
            tboxVCRsltPath.Enabled = boEnabled;
            btnVCRsltPath.Enabled = boEnabled;

            btnVCTCLoad.Enabled = boEnabled;
            btnVCTCReport.Enabled = boEnabled;

            // VCAST Result 
            tboxVCRsltUnitList.Enabled = boEnabled;
            btnVCRsltUnitID.Enabled = boEnabled;

            tboxVCUTRPath.Enabled = boEnabled;
            tboxVCITRPath.Enabled = boEnabled;
            chkVCUTRLoad.Enabled = boEnabled;
            chkIVCTRLoad.Enabled = boEnabled;
            btnVCUTMatrixPath.Enabled = boEnabled;
            btnVCITSResultPath.Enabled = boEnabled;
            btnVCRsltLoad.Enabled = boEnabled;
            tboxVCITAggPath.Enabled = boEnabled;
            btnVCITAggPath.Enabled = boEnabled;


            // excel
            tboxXlsPathSource.Enabled = boEnabled;
            btnXlsPathSource.Enabled = boEnabled;
            tboxXlsPathTarget.Enabled = boEnabled;
            btnXlsPathTarget.Enabled = boEnabled;
            tboxXlsSheetSource.Enabled = boEnabled;
            tboxXlsSheetTarget.Enabled = boEnabled;
            btnXlsCompare.Enabled = boEnabled;
        }

        private int getIntFromTbox(RichTextBox tbox)
        {
            if (tbox == null || string.IsNullOrEmpty(tbox.Text)) {
                return 0;
            }

            int ivalue = 0;
            int.TryParse(tbox.Text, out ivalue);
            return ivalue;
        }

        //------------------------------------------------------------------------------------------------------------
        // progress 
        //------------------------------------------------------------------------------------------------------------
        private void setProgressBarMax(int iMax)
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    probarMain.Maximum = iMax;
                }));
            }
            else {
                probarMain.Maximum = iMax;
            }

            setProgressBarPos(0);
        }

        public void setProgressBarPos(int iPosition)
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    setProgress(iPosition);
                }));
            }
            else {
                setProgress(iPosition);
            }
        }

        public void setProgress(int iPosition)
        {
            if (iPosition <0 || iPosition > probarMain.Maximum) {
                iPosition = probarMain.Maximum;
            }

            probarMain.Value = iPosition;
            labelProgress.Text = string.Format("{0}/{1}", iPosition, probarMain.Maximum);
        }

        private string getTextFromTbox(RichTextBox tbox)
        {
            string text = string.Empty;
            tbox.Invoke(new MethodInvoker(delegate
            {
                text = tbox.Text;
            }));
            return text;
        }

        private void setCaption(DataMode mode)
        {
            string caption = string.Empty;
            switch (mode) {
                case DataMode.QAC_Result:   caption = "QAC Result";         break;
                case DataMode.VC_TestCase:  caption = "VCAST Test Case";    break;
                case DataMode.VC_Matrics:    caption = "VCAST Result";      break;
            }

            if (!string.IsNullOrEmpty(caption)) {
                this.Text = string.Format("TResultParser : {0} ", caption);
            }
        }

        private void DlgOpenFile(RichTextBox tbox, string Filter)
        {
            OpenFileDialog dlgFile = new OpenFileDialog();
            if (!string.IsNullOrEmpty(Filter)) {
                dlgFile.Filter = Filter;
                dlgFile.FilterIndex = 1;
            }

            string path = tbox.Text;
            if (!string.IsNullOrEmpty(path) && File.Exists(path)) {
                dlgFile.InitialDirectory = Path.GetDirectoryName(path);
            }

            if (dlgFile.ShowDialog() != DialogResult.OK) {
                return;
            }

            tbox.Text = dlgFile.FileName;
        }

        private void DlgFolder(RichTextBox tbox)
        {
            FolderBrowserDialog dlgFile = new FolderBrowserDialog();
            string path = tbox.Text;
            if (!string.IsNullOrEmpty(path) && Directory.Exists(path)) {
                dlgFile.SelectedPath = path;
            }

            if (dlgFile.ShowDialog() != DialogResult.OK) {
                return;
            }

            tbox.Text = dlgFile.SelectedPath;
        }
        #endregion

        #region Report
        private string showSaveDlg()
        {
            SaveFileDialog saveDlg = new SaveFileDialog();
            saveDlg.Title = "Save Report";
            saveDlg.DefaultExt = "xlsx";
            saveDlg.Filter = "Excel File(*.xlsx)|*.xlsx|CSV(*.csv)|*.csv";
            return saveDlg.ShowDialog() == DialogResult.OK ? saveDlg.FileName.ToString() : string.Empty;
        }

        private void makingReportProc()
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    makingReport();
                }));
            }

            return;
        }

        public void makingReport()
        {
            setProgressBarMax(0);
            labelElapsedTime.Text = "00:00:00";
            if (string.IsNullOrEmpty(m_ReportPath)) {
                addLog("File Path is empty!!");
                return;
            }

            if (!ConsolMode && File.Exists(m_ReportPath)) {
                if (showMessagbox("File already exist!.\r\nDo you want to overwrite?") == DialogResult.Cancel) {
                    return;
                }
            }

            setComponentEnabled(false);

            startTimer();

            if (m_DataMode == DataMode.QAC_Result) {
                ucQACResult.save(m_ReportPath, !ConsolMode);
            }

            if (m_DataMode == DataMode.VC_TestCase) {
                ucVCTCList.save(m_ReportPath, true);
            }

            if (m_DataMode == DataMode.VC_Matrics) {
                ucVCMatrics.save(m_ReportPath, true);
            }

            addLog("Complete: {0}", m_ReportPath);
            stopTimer();
        }

        private DialogResult showMessagbox(string text)
        {
            if (this.InvokeRequired) {
                return (DialogResult)this.Invoke(new Func<DialogResult>(
                                       () => { return MessageBox.Show(text, "Message", MessageBoxButtons.OKCancel); }));
            }
            else {
                return MessageBox.Show(text, "Message", MessageBoxButtons.OKCancel);
            }
        }
        #endregion

        #region log
        public void addLog(string format, params Object[] args) // for 프로그램 개발 
        {
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

            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    tboxLog.AppendText(data);
                    tboxLog.ScrollToCaret();
                }));
            }
            else {
                tboxLog.AppendText(data);
            }
        }
        #endregion

        #region timer
        private void timerElapsed_Tick(object sender, EventArgs e)
        {
            int tickgap = (Environment.TickCount - m_StartTick)/1000;
            labelElapsedTime.Text = string.Format("{0:D2}:{1:D2}:{2:D2}", tickgap / 3600, (tickgap / 60) % 60, tickgap % 60);
        }

        private void startTimer()
        {
            m_StartTick = Environment.TickCount;
            timerElapsed.Enabled = true;
        }

        private void stopTimer()
        {
            timerElapsed.Enabled = false;
            setComponentEnabled(true);
        }
        #endregion
    }
}
