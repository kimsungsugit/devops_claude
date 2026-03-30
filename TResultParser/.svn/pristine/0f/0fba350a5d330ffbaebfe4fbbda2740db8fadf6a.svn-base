using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using TResultParser.Lib.QAC;
using VectorReporter.Lib.VectorCAST;
using static TResultParser.Lib.VectorCAST.TCBank;

namespace TResultParser.Lib.VectorCAST {
    public class SubFuncManager {
        public Dictionary<string, List<SubFunctionExecution>> m_DicSubFunct;

        private const int LINENO_AGGREGATE_TITLE_2024 = 210;
        private const int LINENO_AGGREGATE_TITLE_2025 = 410;//422;

        private const int LINENO_AGGREGATE_TITLE_END_2024 = 230;
        private const int LINENO_AGGREGATE_TITLE_END_2025 = 434;

        private const int LINENO_AGG_COVERAGE_2024 = 250;
        private const int LINENO_AGG_COVERAGE_2025 = 438;


        public SubFuncManager()
        {
            m_DicSubFunct = new Dictionary<string, List<SubFunctionExecution>>();
            clear();
        }

        public void clear()
        {
            m_DicSubFunct.Clear();
        }

        private List<string> readLine(string line)
        {
            string[] items = line.Split(',');
            return items.ToList();
        }

        public CoverageItem getFunctionCallsCoverate(string subfunctions)
        {
            if (string.IsNullOrEmpty(subfunctions) || !m_DicSubFunct.ContainsKey(subfunctions)) {
                return null;
            }

            CoverageItem coverage = new CoverageItem();
            var passeditems =  m_DicSubFunct[subfunctions].FindAll(item => item.Executed == true);
            coverage.Count = passeditems == null ? 0 : passeditems.Count;
            coverage.Total = m_DicSubFunct[subfunctions].Count;

            return coverage;
        }

        public bool loadITSAggate(VCASTVersion vcastver, string filepath)
        {
            if (string.IsNullOrEmpty(filepath) || !File.Exists(filepath)) {
                return false;
            }

            Debug.Print("AGG File Name : {0}", filepath);

            List<string> lines = new List<string>();
            string line = string.Empty;
            using (StreamReader reader = new StreamReader(filepath)) {
                while ((line = reader.ReadLine()) != null) {
                    lines.Add(line);
                }
            }

            bool isAggCoverage = false;
            string module_name = string.Empty;
            int itemcount = 0;
            int line_aggtitle = (vcastver == VCASTVersion.Ver2021 || vcastver == VCASTVersion.Ver2024) ? LINENO_AGGREGATE_TITLE_2024 : LINENO_AGGREGATE_TITLE_2025;
            int line_aggtitle_end = (vcastver == VCASTVersion.Ver2021 || vcastver == VCASTVersion.Ver2024) ? LINENO_AGGREGATE_TITLE_END_2024 : LINENO_AGGREGATE_TITLE_END_2025;
            int line_aggcoverage = (vcastver == VCASTVersion.Ver2021 || vcastver == VCASTVersion.Ver2024) ? LINENO_AGG_COVERAGE_2024 : LINENO_AGG_COVERAGE_2025;

            for (int index = 0; index < lines.Count; index++) {
                line = lines[index];

                // Check File
                if (index == 1 && !VIMLib.checkStringExists(line, "VectorCAST Report header")) { // Check File Type
                    Debug.Print("File is not a VectorCAST Report(1)");
                    return false;
                }

                if (index >= line_aggtitle && !isAggCoverage) {
                    if (VIMLib.checkStringExists(line, "Aggregate Coverage Report")) { // Check File Type
                        isAggCoverage = true;
                    }
                }

                if (index >= line_aggtitle_end && !isAggCoverage) {
                    Debug.Print("File is not a Aggreagte Coverage Report");
                    return false;
                }

                // <span class="full-cvg success-marker">1 0      *       void g_Ap_Main( void )</span>
                // <span class="full-cvg success-marker"><strong>   244</strong> 7 0      *       static U8 u8s_DataValidCheck( void )</span>
                if (index >= line_aggcoverage && line.IndexOf("<span class=") >= 0 && line.IndexOf("-marker\">") >= 0) {
                    bool success = line.IndexOf("success-marker") >= 0;
                    List<string> coldata = VIMLib.getTableContents(line, "span");
                    if (coldata.Count != 1 && coldata.Count != 4) {
                        Debug.Print("Error: Parameter Count>> Line {0} : {1}", index, line);
                        continue;
                    }

                    string data = coldata.Count == 1 ? coldata[0] : coldata[3];
                    int bpos = data.IndexOf("(");
                    if (bpos < 0) {
                        Debug.Print("Error: Brace>> Line {0} : {1}", index, line);
                        continue;
                    }
                    data = data.Substring(0, bpos);

                    List<string> listdata = HISItem.splitString(data, new char[] { ' '});
                    if (listdata.Count < 3) {
                        Debug.Print("Error: Split>> Line {0} : {1}", index, line);
                        continue;
                    }

                    string module_order = listdata[0];
                    string suborder = listdata[1];
                    string subfunction = listdata[listdata.Count - 1];

                    if (string.IsNullOrEmpty(module_order) || string.IsNullOrEmpty(suborder) || string.IsNullOrEmpty(subfunction)) {
                        Debug.Print("Error: Split >> Line {0} : {1}", index, line);
                        continue;
                    }

                    if (suborder == "0") {
                        module_name = subfunction;
                        if (!m_DicSubFunct.ContainsKey(module_name)) {
                            m_DicSubFunct.Add(module_name, new List<SubFunctionExecution>());
                        }
                        itemcount++;
                    }
                    else {
                        int subidx = m_DicSubFunct[module_name].FindIndex(item => item.Order == suborder);
                        if (subidx < 0) {
                            m_DicSubFunct[module_name].Add(new SubFunctionExecution(suborder, subfunction, success));
                        }
                        else if (!m_DicSubFunct[module_name][subidx].Executed && success) {
                            m_DicSubFunct[module_name][subidx].Executed = success;
                        }
                    }
                }
            }

            return itemcount > 0;
        }

        public void scanResult()
        {
            Debug.Print("============================================================");
            int index = 0;
            foreach (var entry in m_DicSubFunct) {
                var passeditems = entry.Value.FindAll(item => item.Executed == true);
                int passedcount = passeditems == null ? 0 : passeditems.Count;
                int total = entry.Value.Count;
                double ratio = total == 0 ? 0 : Math.Round((double)passedcount * 100 / total, 0);
                Debug.Print("[{0}] {1}, {2}/{3} , {4}%", index++, entry.Key, passedcount, total, ratio);
            }
        }
    }

    #region SubFunctionExecution
    public class SubFunctionExecution {
        public string Order { get; set; }
        public string Name { get; set; }
        public bool Executed { get; set; }

        public SubFunctionExecution(string order, string name, bool executed)
        {
            Order = order;
            Name = name;
            Executed = executed;
        }
    }
    #endregion
}
