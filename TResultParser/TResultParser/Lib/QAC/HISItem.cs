using System.Collections.Generic;

namespace TResultParser.Lib.QAC {
    public class HISItem {

        public enum MatrixItem {
            CALLS = 0,//STCAL 
            RETURN,//(STM19)  
            V_G,// (STCYC) 
            PATH,//(STPTH)    
            LEVEL,//(STMIF)   
            STMT,//(STST3)    
            PARAM,//(STPAR)   
            GOTO,//(STGTO)    
            CALLING,//(STM29)
            Count,
        }

        public string FunctionName{ get; set; }
        private Dictionary<MatrixItem, string> m_dicValues;
        public bool Status { get; set; }
        public string FileName{ get; set; }

        public HISItem(List<string> table_data, string filename)
        {
            m_dicValues = new Dictionary<MatrixItem, string>();
            Status = updateData(table_data);
            FileName = filename;
        }

        public string getMatricValue(MatrixItem item)
        {
            if (m_dicValues.ContainsKey(item)) {
                return m_dicValues[item];
            }

            return string.Empty;
        }

        public void clear()
        {
            Status = false;
            FunctionName = string.Empty;
            FileName = string.Empty;
            m_dicValues.Clear();
        }

        public bool updateData(List<string> table_data)
        {
            clear();
            if (table_data == null || table_data.Count != 5) {
                return false;
            }

            // Check Header
            if (table_data[0].IndexOf("<h4>") < 0) {
                return false;
            }

            if (table_data[1].IndexOf("<table") < 0 || table_data[4].IndexOf("</table>") < 0) {
                return false;
            }

            if (table_data[2].IndexOf("<tr><td") < 0 || table_data[3].IndexOf("<tr><td") < 0) {
                return false;
            }

            // Get Function Name 
            FunctionName = getFunctionName(table_data[0]);
            if (string.IsNullOrEmpty(FunctionName)) {
                return false;
            }

            // Value 
            List<string> listMatrix = splitTableData(true, table_data[2]);
            List<string> listValue = splitTableData(false, table_data[3]);
            if (listMatrix == null || listValue == null || listMatrix.Count != listValue.Count) {
                clear();
                return false;
            }

            for (int idx = 1; idx < listMatrix.Count; idx++) {
                MatrixItem item = cvrtMatrixItem(listMatrix[idx]);
                if (item == MatrixItem.Count) {
                    return false;
                }

                m_dicValues.Add(item, listValue[idx]);
            }

            return true;
        }

        private MatrixItem cvrtMatrixItem(string caption)
        {
            for (MatrixItem item = MatrixItem.CALLS; item < MatrixItem.Count; item++) {
                if (caption.IndexOf(getTitle(item, true)) >= 0) {
                    return item;
                }
            }

            return MatrixItem.Count;
        }
        private List<string> splitTableData(bool boMatrix, string data)
        {
            List<string> list = new List<string>();
            if ((boMatrix && data.IndexOf("Metric") < 0) || (!boMatrix && data.IndexOf("Values") < 0)) {
                return null;
            }


            List<string> listspt = HISItem.splitString(data, new char[] { '<', '>' });
            foreach (string item in listspt) {
                if((item.IndexOf("tr") >= 0 && item != "Metric") || item.IndexOf("td") >= 0){
                    continue;
                }

                list.Add(item);
            }

            return list;
        }

        public static List<string> splitString(string data, char[] delimiter)
        {
            List<string> list = new List<string>();
            if (string.IsNullOrEmpty(data)) {
                return list;
            }

            string[] listItems = data.Split(delimiter);
            foreach (string item in listItems) {
                if (!string.IsNullOrEmpty(item)) {
                    list.Add(item.Trim());
                }
            }

            return list;
        }

        private string getFunctionName(string data)
        {
            int start = data.IndexOf(":");
            int end = data.IndexOf("</h4>");

            return data.Substring(start+1, end - start-1);
        }

        public static string getTitle(MatrixItem item, bool name)
        {
            switch (item) {
                case MatrixItem.CALLS:
                    return name ? "CALLS" : "STCAL";
                case MatrixItem.RETURN:
                    return name ? "RETURN" : "STM19";
                case MatrixItem.V_G:
                    return name ? "v(G)" : "STCYC";
                case MatrixItem.PATH:
                    return name ? "PATH" : "STPTH";
                case MatrixItem.LEVEL:
                    return name ? "LEVEL" : "STMIF";
                case MatrixItem.STMT:
                    return name ? "STMT" : "STST3";
                case MatrixItem.PARAM:
                    return name ? "PARAM" : "STPAR";
                case MatrixItem.GOTO:
                    return name ? "GOTO" : "STGTO";
                case MatrixItem.CALLING:
                    return name ? "CALLING" : "STM29";
            }
            return string.Empty;
        }

    }
}
