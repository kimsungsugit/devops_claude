using System.Collections.Generic;
using static TResultParser.Lib.QAC.HISItem;

namespace TResultParser.Lib.QAC {
    public class MatrixSpec {

        public MatrixItem MatrixType;
        public int SpecCount {  get { return ListSpec == null ? 0 : ListSpec.Count; } }
        public List<int> ListSpec;


        public MatrixSpec(MatrixItem item, params int[] specList)
        {
            MatrixType = item;

            ListSpec = new List<int>();
            foreach (int spec in specList) {
                ListSpec.Add(spec);
            }
        }

        public void clear(bool dataonly)
        {
            if (SpecCount == 0) {
                return;
            }

            if (dataonly) {
                for (int index = 0; index < SpecCount; index++) {
                    ListSpec[index] = 0;
                }

            }
            else {
                ListSpec.Clear();
            }
        }
    }
}
