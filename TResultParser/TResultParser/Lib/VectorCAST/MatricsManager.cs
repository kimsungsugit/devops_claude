using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using static TResultParser.Lib.VectorCAST.TCBank;

namespace VectorReporter.Lib.VectorCAST {
    public class MatricsManager {

        private const int LINENO_ENVIRONMENT_NAME_VER2021 = 207;
        private const int LINENO_ENVIRONMENT_NAME_VER2024 = 232;
        private const int LINENO_ENVIRONMENT_NAME_VER2025 = 418;

        private const int LINENO_COVERAGETYPE_VER2021 = 220;
        private const int LINENO_COVERAGETYPE_VER2024 = 245;
        private const int LINENO_COVERAGETYPE_VER2025 = 429;

        private static readonly object locker = new object();
        public Dictionary<string, MatixDataBank> DicStatement;  // Unit 
        public Dictionary<string, MatixDataBank> DicFunctions;  // Integration 

        #region Instance
        private static MatricsManager m_instance = null;
        public static MatricsManager getInstance()
        {
            if (m_instance == null) {
                m_instance = new MatricsManager();
            }
            return m_instance;
        }
        #endregion

        public MatricsManager()
        {
            DicStatement = new Dictionary<string, MatixDataBank>();
            DicFunctions = new Dictionary<string, MatixDataBank>();
        }

        public void clear()
        {
            DicStatement.Clear();
            DicFunctions.Clear();
        }

        public Dictionary<string, MatixDataBank> getDataBank(MatricsType mtype)
        {
            if (mtype == MatricsType.Statement) {
                return DicStatement;
            }
            else if (mtype == MatricsType.Functions) {
                return DicFunctions;
            }

            return null;
        }

        private string getUnitNameOfsubprogram(string subprogram)
        {
            if (string.IsNullOrEmpty(subprogram)) {
                return string.Empty;
            }

            foreach (var entry in DicStatement) {
                if (entry.Value.existsubprogram(subprogram)) {
                    return entry.Key;
                }
            }

            return string.Empty;
        }

        public bool updateStatementFunctionCalled(bool inline, string unit, string subprogram, CoverageItem FunctionsCall)
        {
            string unit_name = unit;
            if (inline) {
                string temp = getUnitNameOfsubprogram(subprogram);
                if (!string.IsNullOrEmpty(temp) && unit != temp) {
                    unit_name = temp;
                    Debug.Print("unit name change : {0} -> {1} [{2}]", unit, temp, subprogram);
                }
            }

            if (!DicStatement.ContainsKey(unit_name)) {
                return false;
            }

            return DicStatement[unit_name].updateFunctionCalled(subprogram, FunctionsCall);
        }

        public int getFunctionCalledCount()
        {
            int count = 0;
            foreach (var entry in DicStatement) {
                foreach (var bank in entry.Value.DicData) {
                    if (((MatricStatementItem)bank.Value).IsFunction) {
                        count++;
                    }
                }
            }

            return count;
        }

        public int getFunctionCount()
        {
            int count = 0;
            foreach (var entry in DicStatement) {
                count += entry.Value.DicData.Count;
            }

            return count;
        }

        private bool updateBank(MatricsType matrictype, List<IMatrixPrototype> listdata)
        {
            if (matrictype == MatricsType.None || listdata == null) {
                return false;
            }

            Dictionary<string, MatixDataBank> dicBank = getDataBank(matrictype);

            foreach (var item in listdata) {
                string key = (matrictype == MatricsType.Statement) ? item.UnitName : item.ID;

                if (!dicBank.ContainsKey(key)) {
                    dicBank.Add(key, new MatixDataBank(matrictype, item.UnitName));
                }

                dicBank[key].add(item);
            }

            return true;
        }

        private int getEnvironmentNameLineNo(VCASTVersion vcastVer)
        {
            switch (vcastVer) {
                case VCASTVersion.Ver2021: return LINENO_ENVIRONMENT_NAME_VER2021;
                case VCASTVersion.Ver2024: return LINENO_ENVIRONMENT_NAME_VER2024;
                case VCASTVersion.Ver2025: return LINENO_ENVIRONMENT_NAME_VER2025;
            }

            return -1;
        }

        private int getCoverageTypeLineNo(VCASTVersion vcastVer)
        {
            switch (vcastVer) {
                case VCASTVersion.Ver2021: return LINENO_COVERAGETYPE_VER2021;
                case VCASTVersion.Ver2024: return LINENO_COVERAGETYPE_VER2024;
                case VCASTVersion.Ver2025: return LINENO_COVERAGETYPE_VER2025;
            }

            return -1;
        }

        public bool readFile(VCASTVersion vcastVer, MatricsType matrictype, string filepath)
        {
            MatricsType mtype = MatricsType.None;
            List<IMatrixPrototype> listdata = new List<IMatrixPrototype>();
            string unit_pre = string.Empty;
            string id = string.Empty;

            bool use_inline = vcastVer == VCASTVersion.Ver2025;

   //         Debug.Print("========================={0}", Path.GetFileName(filepath));
            List<string> lines = new List<string>();
            string line = string.Empty;
            using (StreamReader reader = new StreamReader(filepath)) {
                while ((line = reader.ReadLine()) != null) {
                    lines.Add(line);
                }
            }

            for (int index = 0; index < lines.Count; index++) {
                line = lines[index];

                // Check File
                if (index == 1 && !VIMLib.checkStringExists(line, "VectorCAST Report header")) { // Check File Type
                    Debug.Print("File is not a VectorCAST Report(1)");
                    return false;
                }

                int targetindex = getEnvironmentNameLineNo(vcastVer);
                if (index == targetindex && line.IndexOf("<tr><th>Environment Name</th>") >= 0) {
                    id = VIMLib.EnvironmentName(line);
                }

                targetindex = getCoverageTypeLineNo(vcastVer);
                if (index == targetindex && line.IndexOf("<h3 id=\"coverage_type\">") >= 0 ) { // Matric Mode
                    mtype = VIMLib.getMatricsType(line);
                    if (mtype == MatricsType.None ) {
                        Debug.Print("File is not a VectorCAST Report(2)");
                        return false;
                    }
                }

                targetindex += 4;
                //<th class="col_unit">Unit</th><th class="col_subprogram">Subprogram</th><th class="col_complexity">Complexity</th><th class="col_metric">Statements</th>
                if (index == targetindex && line.IndexOf("<th class=\"col_unit\">") >= 0) { // header
                    List<string> listHeader = VIMLib.getTableContents(line, "th");
                    if (listHeader == null && !checkListCount(mtype, listHeader)) {
                        Debug.Print("File is not a VectorCAST Report(3)");
                        return false;
                    }
                }

                targetindex += 5;
                if (index >= targetindex && line.IndexOf("<td class=\"col_unit\">") >= 0) {
                    List<string> coldata = VIMLib.getTableContents(line, "td");
                    if (!checkListCount(mtype, coldata)) {
                        continue;
                    }

                    string unit_name = coldata[0];
                    if (unit_name == VIMLib.EMPTY_DATA) {
                        if (string.IsNullOrEmpty(unit_pre)) {
                            Debug.Print("Unit Name Is Empty!!");
                            return false;
                        }

                        coldata[0] = unit_pre;
                    }
                    else {
                        unit_pre = coldata[0];
                    }

                    IMatrixPrototype item = null;
                    if (mtype == MatricsType.Statement) {
                        item = new MatricStatementItem(id, coldata);
                    }

                    if (mtype == MatricsType.Functions) {
                        item = new MatricFunCallItem(id, coldata);
                        if (DicStatement.Count > 0 && ((MatricFunCallItem)item).Functions.Count > 0) {
                            if (!updateStatementFunctionCalled(use_inline, item.UnitName, item.SubProgram, ((MatricFunCallItem)item).FunctionsCall)) {
                                Debug.Print("[{0}] {1} : Error", item.UnitName, item.SubProgram);
                            }
                        }
                    }

                    if (item != null && item.IsValid) {
                        listdata.Add(item);
                    }
                }

            }

            return updateBank(matrictype, listdata);
        }

        private bool checkListCount(MatricsType matrictype, List<string> list)
        {
            if (list == null || (list.Count < 4 && matrictype == MatricsType.Statement) || (list.Count < 4 && matrictype == MatricsType.Functions)) {
                return false;
            }

            if (matrictype == MatricsType.Functions && list[0].IndexOf("TOTALS") >= 0) {
                return false;
            }

            return true;
        }
    }
}

