using System.Collections.Generic;

namespace VectorReporter.Lib.VectorCAST {
    public static class VIMLib {
        
        public const string EMPTY_DATA = "&nbsp;";

        public static bool checkStringExists(string org, string data)
        {
            if (string.IsNullOrEmpty(org) || string.IsNullOrEmpty(data)) {
                return false;
            }

            return org.IndexOf(data) >= 0;
        }


        public static List<string> getTableContents(string line, string param)
        {
            if (string.IsNullOrEmpty(line) || line.IndexOf(param) < 0) {
                return null;
            }

            List<string> list = new List<string>();
            List<string> listspt = splitString(line, new char[] { '<', '>' });
            foreach (string item in listspt) {
                if (item.IndexOf(param +" ") >=0 || item.IndexOf("/" +param ) >= 0|| string.IsNullOrEmpty(item)) {
                    continue;
                }

                list.Add(item);
                //           addLog(item);
            }
            return list;
        }

        public static bool checkStringExists(string org, string[] listparam)
        {
            if (string.IsNullOrEmpty(org) || listparam == null || listparam.Length == 0) {
                return false;
            }

            foreach (string param in listparam) {
                if (org.IndexOf(param) >= 0) {
                    return true;
                }
            }

            return false;
        }

        public static List<string> getTableRowDataOnly(string line)
        {
            if (string.IsNullOrEmpty(line)) {
                return null;
            }

            List<string> list = new List<string>();
            List<string> listspt = splitString(line, new char[] { '<', '>' });
            string[] listparam = new string[] { "tr", "th", "td" };
            foreach (string item in listspt) {
                if (string.IsNullOrEmpty(item) || (checkStringExists(item, listparam) && (item.Length == 2 || item.Length == 3))) {
                    continue;
                }

                list.Add(item);
                //           addLog(item);
            }
            return list;
        }

        public static string getOneTdValue(string line)
        {
            if (string.IsNullOrEmpty(line) || line.IndexOf("td") < 0) {
                return null;
            }

            List<string> listspt = splitString(line, new char[] { '<', '>' });
            foreach (string item in listspt) {
                if (string.IsNullOrEmpty(item) || item.IndexOf("td ") >= 0|| 
                    (item.IndexOf("td") >= 0 && item.Length == 2) || item.IndexOf("/td") >= 0) { // 변수에 td가 포함된 경우 제외를 위해 수정 
                    continue;
                }
                string retValue = item;

                if (item.IndexOf("&nbsp;") > 0) {
                    retValue = item.Replace("&nbsp;", "");
                }
                return retValue;
            }
            return string.Empty;
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


        public static string substring(string data, string delimiter, bool pre )
        {
            List<string> list = new List<string>();
            if (string.IsNullOrEmpty(data) || string.IsNullOrEmpty(delimiter)) {
                return string.Empty;
            }

            int index = data.IndexOf(delimiter);
            if (index < 0) {
                return string.Empty;
            }

            if (pre) {
                return data.Substring(0, index);
            }
            else {
                int dellength = delimiter.Length;
                return data.Substring(index + dellength, data.Length - index - dellength);
            }
        }

        public static string EnvironmentName(string org)
        {
            if (string.IsNullOrEmpty(org)) {
                return string.Empty;
            }

            int start = org.IndexOf("<td>");
            int end = org.IndexOf("</td>");

            if (start < 0 || end < 0) {
                return string.Empty;
            }

            string data = org.Substring(start + 4, end - start - 4);
            return data.Trim();
        }


        public static MatricsType getMatricsType(string org)
        {
            if (string.IsNullOrEmpty(org)) {
                return MatricsType.None;
            }

            int start = org.IndexOf(">");
            int end = org.IndexOf("</h3>");

            if (start < 0 || end < 0) {
                return MatricsType.None;
            }

            string data = org.Substring(start + 1, end - start - 1);
            data = data.Trim();
            if (data == "Statement" || data == "Statement+Branch") {
                return MatricsType.Statement;
            }

            if (data == "Function" || data == "Function+Function Call") {
                return MatricsType.Functions;
            }

            return MatricsType.None;
        }


        public static int strToInt(string data)
        {
            int ivalue = 0;
            int.TryParse(data, out ivalue);
            return ivalue;
        }

    }
}
