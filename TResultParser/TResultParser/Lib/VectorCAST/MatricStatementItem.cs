using System.Collections.Generic;

namespace VectorReporter.Lib.VectorCAST {
    public class MatricStatementItem: IMatrixPrototype {

        public MatricsType MType { get { return MatricsType.Statement; } }
        public string UnitID { get; set; }

        public string ID { get; set; } 
        public string UnitName { get; set; }
        public string SubProgram { get; set; }
        public int Complexity { get; set; }

        public CoverageItem Statements{ get; set; }
        public CoverageItem Branches { get; set; }

        // Integration Test 
        public bool IsFunction { get; set; }
        public CoverageItem FunctionsCall { get; set; }

        public bool IsValid { get; set; }

        public MatricStatementItem( string id, List<string> list)
        {
            clear();
            ID = id;
            if (list != null && list.Count >=4) {
                UnitName = list[0];
                SubProgram = list[1];
                Complexity = VIMLib.strToInt(list[2]);
                Statements = new CoverageItem(list[3]); // Statements
                if (list.Count > 4) {
                    Branches = new CoverageItem(list[4]); // branches
                }
                IsValid = true;
            }
        }

        public MatricStatementItem()
        {
            clear();
            UnitID = string.Empty;
            UnitName = "Total";
            Statements = new CoverageItem();
            Branches = new CoverageItem();
            FunctionsCall = new CoverageItem();

            IsValid = true;
        }

        public void clear()
        {
            ID = string.Empty;
            SubProgram = string.Empty;
            Complexity = 0;
            Statements = null;
            Branches = null;

            IsFunction = false;
            FunctionsCall = null;
            IsValid = false;
        }

        public override string ToString()
        {
            string data = string.Format("[{0}:{1}] {2}, {3} S:{4} ", ID, UnitName, SubProgram, Complexity, Statements.Coverage);
            if (Branches != null) {
                data += string.Format(" B:{0}", Branches.Coverage);
            }

            if (FunctionsCall != null) {
                data += string.Format(" B:{0}", FunctionsCall.Coverage);
            }

            return data;
        }

    }
}
