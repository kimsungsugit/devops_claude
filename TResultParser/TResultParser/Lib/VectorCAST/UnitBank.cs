using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using TResultParser.Lib.Component;

namespace TResultParser.Lib.VectorCAST {
    public class UnitBank {

        private Dictionary<string, string> m_dicUnit;
        public int Count { get { return m_dicUnit.Count; } }

        public UnitBank()
        {
            m_dicUnit = new Dictionary<string, string>();
        }

        public void clear()
        {
            m_dicUnit.Clear();
        }

        public string getUnitID(string funtionname)
        {
            string func_name = funtionname.ToLower();

            if (m_dicUnit.ContainsValue(func_name)) {
                return m_dicUnit.FirstOrDefault(x => x.Value == func_name).Key;
            }
            else {
                return string.Empty;
            }
        }

        private List<string> readLine(string line)
        {
            string[] items = line.Split(',');
            return items.ToList();
        }

        #region Unit File 
        public bool loadUnitData(string filepath)
        {
            m_dicUnit.Clear();
            if (string.IsNullOrEmpty(filepath) || !File.Exists(filepath)) {
                return false;
            }

            if (Path.GetExtension(filepath).ToLower() == ".csv") { // CSV File
                string[] lines = File.ReadAllLines(filepath);
                for (int lineno = 0; lineno < lines.Count(); lineno++) {
                    string line = lines[lineno];
                    if (string.IsNullOrEmpty(line) || lineno < 1) {
                        continue;
                    }

                    List<string> listdata = readLine(line);
                    if (listdata.Count != 3) {
                        continue;
                    }

                    m_dicUnit.Add(listdata[1], listdata[2].ToLower());
                }
            }
            else { // excel 
                XlsxManager excel = new XlsxManager();
                if (!excel.open(filepath)) {
                    Debug.Print("Create File Error : {0}", filepath);
                    return false;
                }

                int col_max = excel.getColumnMaxCount();
                int row_max = excel.getRowMaxCount();

                if (col_max ==3 && row_max > 1) {
                    for (int row = 1; row < row_max; row++) {

                        string id = excel.getCellValue(row + 1, 2);
                        string name = excel.getCellValue(row + 1, 3);
                        if (string.IsNullOrEmpty(id) || string.IsNullOrEmpty(name)) {
                            continue;
                        }

                        m_dicUnit.Add(id, name.ToLower());
                    }
                }

                excel.close(false, false);
            }

            return m_dicUnit.Count > 0;
        }

        private List<string> splitTextByColon(string text)
        {
            List<string> list = new List<string>();
            if (string.IsNullOrEmpty(text)) {
                return list;
            }

            string[] listItems = text.Split(new char[] { '\t' });
            for (int item = 0; item < listItems.Length; item++) {
                string data = listItems[item].Trim();
                if (!string.IsNullOrEmpty(data)) {
                    list.Add(data);
                }
            }

            return list;
        }
        #endregion
    }
}
