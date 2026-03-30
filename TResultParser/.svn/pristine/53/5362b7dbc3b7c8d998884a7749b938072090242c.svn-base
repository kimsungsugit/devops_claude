using System.Collections.Generic;

namespace VectorReporter.Lib.VectorCAST {
    public class MatricFunCallItem : IMatrixPrototype {
        public MatricsType MType { get { return MatricsType.Functions; } }
        public string UnitID { get; set; } 

        public string ID { get { return UnitName == string.Empty ? FileID : string.Format("{0}:{1}", FileID, UnitName); } }
        public string FileID { get; set; }
        public string UnitName { get; set; }
        public string SubProgram { get; set; }
        public int Complexity { get; set; }

        public CoverageItem Functions{ get; set; }
        public CoverageItem FunctionsCall { get; set; }
        
        public bool IsValid { get; set; }
        

        public MatricFunCallItem(string id,  List<string> list)
        {
            clear();
            FileID = id;
            if (list.Count >=4 ) {
                UnitName = list[0];
                SubProgram = list[1];
                Complexity = VIMLib.strToInt(list[2]);
                Functions = new CoverageItem(list[3]);
                if (list.Count >= 5) {
                    FunctionsCall = new CoverageItem(list[4]);
                }
                IsValid = true;
            }
        }

        public MatricFunCallItem()
        {
            clear();
            UnitID = string.Empty;
            UnitName = "Total";
            Functions = new CoverageItem();
            FunctionsCall = new CoverageItem();
            IsValid = true;
        }

        public void clear()
        {
            FileID = string.Empty;
            SubProgram = string.Empty;
            Complexity = 0;

            Functions = null;
            FunctionsCall = null;
            IsValid = false;
        }

        public override string ToString()
        {
            string data = string.Format("[{0}]{1} : {2} - {3} {4} ", ID,  UnitName, SubProgram, Complexity, Functions.Coverage);
            if (FunctionsCall != null) {
                data += FunctionsCall.Coverage;
            }
            return data;
        }
    }
}
