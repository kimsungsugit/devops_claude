using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using static TResultParser.Lib.QAC.HISItem;

namespace TResultParser.Lib.QAC {
    public class QACDataManager {

        #region variables
        public enum QACColumn {
            Index = 0,
            Function,
            V_G,// STCYC
            LEVEL,// STMIF
            CALLING, // STM29,
            CALLS,//STCAL,
            File,
            Count,
        }

        private const int LINENO_TITLE_OLD = 112;
        private const int LINENO_TITLE_NEW = 117;

        private const int LINENO_FILESTART_OLD = 121;
        private const int LINENO_FILESTART_NEW = 127;

        public Dictionary<MatrixItem, MatrixSpec> DicSpec;
        public Dictionary<MatrixItem, MatrixSpec> DicSpecOverCount;

        public List<HISItem> ListResult;
        #endregion


        public QACDataManager()
        {
            DicSpec = new Dictionary<MatrixItem, MatrixSpec>();
            DicSpecOverCount = new Dictionary<MatrixItem, MatrixSpec>();
            ListResult = new List<HISItem>();

            buildSpec();
            clear();
        }


        #region main function
        public bool readFile(bool oldversion, string path)
        {
            clear();
        //    QACFilePath = path;
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) {
                return false;
            }

            using (StreamReader reader = new StreamReader(path)) {

                string matrix_filename = string.Empty;
                string line = string.Empty;
                int index = 0;
                List<string> list = new List<string>();
                while ((line = reader.ReadLine()) != null) {

                    int targetline = oldversion ? LINENO_TITLE_OLD : LINENO_TITLE_NEW;
                    // Check File
                    if (index == targetline) { // Check File Type
                        if (!checkStringExists(line, "<title>") || 
                            (oldversion && !checkStringExists(line, "PRQA HIS Metrics Report")) ||
                             (!oldversion && !checkStringExists(line, "Helix QAC HIS Metrics Report"))){
                            Debug.Print("File is not a PRQA HIS Metrics Report");
                            return false;
                        }
                    }

                    targetline = oldversion ? LINENO_FILESTART_OLD : LINENO_FILESTART_NEW;
                    if (index >= targetline) {
                        if (line.IndexOf("<h3>File") >= 0 || line.IndexOf("<h4>Function") >= 0) {
                            if (line.IndexOf("<h3>File") >= 0) {
                                matrix_filename = getFilePath(line);
                            }

                            list.Clear();
                            list.Add(line);
                        }
                        if (line.IndexOf("<table") >= 0 || line.IndexOf("<tr><td") >= 0) {
                            list.Add(line);
                        }

                        if (line.IndexOf("</table>") >= 0) {
                            list.Add(line);

                            HISItem hisitem = new HISItem(list, matrix_filename);
                            if (hisitem.Status) {
                                ListResult.Add(hisitem);
                            }
                        }
                    }
                    index++;
                }
    //            addTotalData();
            }
            return (ListResult != null && ListResult.Count > 0);
        }
        #endregion


        public void updateSpecOverCount(MatrixItem item, int warninglevel)
        {
            if (warninglevel < 0 || !DicSpecOverCount.ContainsKey(item)) {
                return;
            }

            DicSpecOverCount[item].ListSpec[warninglevel] = DicSpecOverCount[item].ListSpec[warninglevel] + 1;
        }

        public string getSpecString(MatrixItem matrix, int warnlevel)
        {
            if (!DicSpec.ContainsKey(matrix) || warnlevel == 0) {
                return string.Empty;
            }

            MatrixSpec spec = DicSpec[matrix];
            if (warnlevel > spec.SpecCount) {
                return string.Empty;
            }

            int threshold = spec.ListSpec[warnlevel - 1];
            return string.Format("{0} >= {1}", HISItem.getTitle(matrix, false), threshold);
        }

        public int checkWarningLevel(MatrixItem matrix, string value)
        {
            if (!DicSpec.ContainsKey(matrix) || string.IsNullOrEmpty(value)) {
                return 0;
            }

            MatrixSpec spec = DicSpec[matrix];
            if (spec == null || spec.SpecCount == 0) {
                return 0;
            }

            int matrix_value = 0;
            int.TryParse(value, out matrix_value);

            for (int index = spec.SpecCount - 1; index >= 0; index--) {
                if (matrix_value >= spec.ListSpec[index]) {
                    return index + 1;
                }
            }

            return 0;
        }

        public static MatrixItem[] getMatrixList()
        {
            return new MatrixItem[] { MatrixItem.V_G, MatrixItem.LEVEL, MatrixItem.CALLING, MatrixItem.CALLS };
        }

        public int getColumnIndexOfMatrixItem(MatrixItem matrix)
        {
            MatrixItem[] list = getMatrixList();
            int index = 0;
            int default_col = 2;
            foreach (MatrixItem item in list) {
                if (item == matrix) {
                    return default_col + index;
                }

                index++;
            }

            return -1;
        }

        #region Data
        private string getFilePath(string org)
        {
            if (string.IsNullOrEmpty(org) || org.IndexOf("<h3>File:") < 0) {
                return string.Empty;
            }

            int start = org.IndexOf(":");
            int end = org.IndexOf("</h3>");

            if (start < 0 || end < 0) {
                return string.Empty;
            }

            return org.Substring(start + 1, end - start - 1);
        }

        private bool checkStringExists(string org, string data)
        {
            if (string.IsNullOrEmpty(org) || string.IsNullOrEmpty(data)) {
                return false;
            }

            return org.IndexOf(data) >= 0;
        }

        private void buildSpec()
        {
            DicSpec = new Dictionary<MatrixItem, MatrixSpec>();
            DicSpec.Add(MatrixItem.V_G, new MatrixSpec(MatrixItem.V_G, 11, 21, 31));
            DicSpec.Add(MatrixItem.LEVEL, new MatrixSpec(MatrixItem.LEVEL, 6, 11));
            DicSpec.Add(MatrixItem.CALLING, new MatrixSpec(MatrixItem.CALLING, 6, 11));
            DicSpec.Add(MatrixItem.CALLS, new MatrixSpec(MatrixItem.CALLS, 8, 13));


            DicSpecOverCount = new Dictionary<MatrixItem, MatrixSpec>();
            DicSpecOverCount.Add(MatrixItem.V_G, new MatrixSpec(MatrixItem.V_G, 0, 0, 0, 0));
            DicSpecOverCount.Add(MatrixItem.LEVEL, new MatrixSpec(MatrixItem.LEVEL, 0, 0, 0));
            DicSpecOverCount.Add(MatrixItem.CALLING, new MatrixSpec(MatrixItem.CALLING, 0, 0, 0));
            DicSpecOverCount.Add(MatrixItem.CALLS, new MatrixSpec(MatrixItem.CALLS, 0, 0, 0));
        }

        public void clear()
        {
            if (ListResult != null) {
                ListResult.Clear();
            }

            if (DicSpecOverCount != null) {
                foreach (var entry in DicSpecOverCount) {
                    entry.Value.clear(true);
                }
            }
        }
        #endregion
    }
}
