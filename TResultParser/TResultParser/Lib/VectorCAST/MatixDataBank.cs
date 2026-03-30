using System.Collections.Generic;

namespace VectorReporter.Lib.VectorCAST {
    public class MatixDataBank {
        public MatricsType MType { get; set; }
        public string UnitName { get; set; }
        public int ItemCount { get { return DicData.Count; } }
        public Dictionary<string, IMatrixPrototype> DicData;

        public MatixDataBank(MatricsType mtype, string unit )
        {
            MType = mtype;
            UnitName = unit;
            DicData = new Dictionary<string, IMatrixPrototype>();
        }

        public bool add(IMatrixPrototype item)
        {
            if (MType != item.MType || UnitName!= item.UnitName) {
                return false;
            }

            if (!DicData.ContainsKey(item.SubProgram)) {
                DicData.Add(item.SubProgram, item);
            }

            return true;
        }

        public bool updateFunctionCalled(string subprogram, CoverageItem FunctionsCall)
        {
            if (!DicData.ContainsKey(subprogram)) {
                return false;
            }

            ((MatricStatementItem)DicData[subprogram]).IsFunction = true;
            if (FunctionsCall != null) {
                CoverageItem Item = ((MatricStatementItem)DicData[subprogram]).FunctionsCall;
                if (Item == null || (Item != null  && Item.Count < FunctionsCall.Count)) { 
                    ((MatricStatementItem)DicData[subprogram]).FunctionsCall = FunctionsCall;
                }
            }
            return true;
        }

        public bool existsubprogram(string subprogram)
        {
            if (string.IsNullOrEmpty(subprogram)) {
                return false;
            }

            return DicData.ContainsKey(subprogram);
        }

        public MatixDataBank clone()
        {
            MatixDataBank item = new MatixDataBank(MType, UnitName);
            foreach (var entry in DicData) {
                item.DicData.Add(entry.Key, entry.Value);
            }

            return item;
        }
    }
}
