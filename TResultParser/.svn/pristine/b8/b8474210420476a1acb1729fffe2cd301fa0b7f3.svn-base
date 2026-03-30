using System;
using System.Windows.Forms;

namespace TResultParser.GUI.Controls {
    public partial class UCDataType : UserControl {

        #region variables
        public enum DataMode {
            QAC_Result = 1,
            VectorCAST,
            VC_TestCase,
            VC_Matrics,
            Xls_Compare,
            Count,
        }

        public delegate void SetDataModeEvent(DataMode mode);
        SetDataModeEvent setDataMode;
        #endregion

        #region event
        public UCDataType()
        {
            InitializeComponent();
        }

        private void UCDataType_Load(object sender, EventArgs e)
        {
            init();
        }

        private void fgridDataMode_MouseClick(object sender, MouseEventArgs e)
        {
            var ht = fgridDataMode.HitTest();
            int row = ht.Row;
            if (row == (int)DataMode.QAC_Result) {
                setDataMode(DataMode.QAC_Result);
            }

            if (row == (int)DataMode.VC_TestCase) {
                setDataMode(DataMode.VC_TestCase);
            }

            if (row == (int)DataMode.VC_Matrics) {
                setDataMode(DataMode.VC_Matrics);
            }

            if (row == (int)DataMode.Xls_Compare) {
                setDataMode(DataMode.Xls_Compare);
            }
        }

        private void UCDataType_SizeChanged(object sender, EventArgs e)
        {
            setDataModeGridWidth();
        }
        #endregion

        #region  
        public void setDelegate(SetDataModeEvent getdm)
        {
            setDataMode = getdm;
        }

        public void selectDataMode(DataMode datamode)
        {
            fgridDataMode.Focus();
            fgridDataMode.Select((int)datamode, 0); 
        }

        private void init()
        {
            fgridDataMode.Rows.Count = 1;
            fgridDataMode[0, 0] = "DataMode";

            string[] captions = new string[] { "QAC Result", "VectorCAST", "Test Case", "Test Matrics", "Excel Compare" };
            int index = 0;
            for (int mode = (int)DataMode.QAC_Result; mode < (int)DataMode.Count; mode++) {
                fgridDataMode.Rows.Add();
                fgridDataMode[mode, 0] = captions[index++];
                fgridDataMode.Rows[mode].IsNode = true;
                fgridDataMode.Rows[mode].Node.Level = (mode <= (int)DataMode.VectorCAST || mode >= (int)DataMode.Xls_Compare) ? 0 : 1;
            }

            setDataModeGridWidth();
        }

        private void setDataModeGridWidth()
        {
            if (this.InvokeRequired) {
                this.Invoke(new Action(delegate () {
                    fgridDataMode.Cols[0].Width = fgridDataMode.Width - 10;
                }));
            }
            else {
                fgridDataMode.Cols[0].Width = fgridDataMode.Width - 10;
            }
        }
        #endregion
    }
}
