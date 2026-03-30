using System.Collections.Generic;
using System.Linq;

namespace TResultParser.Lib.VectorCAST {
    public class TCManager {

        #region variable 
        private static readonly object locker = new object();
        
        public List<TCBank> ListTestCase { get; set; }
        public List<TCBank> ListActResult { get; set; }
        public int MaxInputCount { get; set; }
        public int MaxExpResultCount { get; set; }
        public int MaxActResultCount { get; set; }
        #endregion

        public TCManager()
        {
            ListTestCase = new List<TCBank>();
            ListActResult = new List<TCBank>();
            clear();
        }
        
        public bool addItem(TCBank item)
        {
            if (!updateCount(item)) {
                return false;
            }

            lock (locker) {
                if (item.MaxActResultCount > 0) {
                    ListActResult.Add(item);
                }
                else {
                    ListTestCase.Add(item);
                }
                return true;
            }
        }

        public void sortByTCID()
        {
            if (ListTestCase.Count != 0) {
                foreach (var item in ListTestCase) {
                    item.sort();
                }
            }

            if (ListActResult.Count != 0) {
                foreach (var item in ListActResult) {
                    item.sort();
                }
            }
        }

        public TCBank getActualData(string envirnment)
        {
            if (ListActResult == null) {
                return null;
            }

            return ListActResult.Find(x => x.Envirnment == envirnment);
        }

        private List<string> getListOfTestID(Dictionary<string, TestResultItem> dicarslt)
        {
            List<string> list = new List<string>();
            if (dicarslt == null || dicarslt.Count == 0) {
                return list;
            }

            string tcname_backup = string.Empty;
            foreach (var entry in dicarslt) {
                string tcname = entry.Value.Header.TCName;
                if (tcname_backup != tcname) {
                    list.Add(tcname);
                    tcname_backup = tcname;
                }
            }

            return list;
        }

        private bool updateCount(TCBank item)
        {
            if (!item.IsValid) {
                return false;
            }

            lock (locker) {
                if (item.MaxInputCount > MaxInputCount) {
                    MaxInputCount = item.MaxInputCount;
                }

                if (item.MaxExpResultCount > MaxExpResultCount) {
                    MaxExpResultCount = item.MaxExpResultCount;
                }

                if (item.MaxActResultCount > MaxActResultCount) {
                    MaxActResultCount = item.MaxActResultCount;
                }

                return true;
            }
        }

        public void clear()
        {
            MaxInputCount = 0;
            MaxExpResultCount = 0;
            MaxActResultCount = 0;

            lock (locker) {
                ListTestCase.Clear();
                ListActResult.Clear();
            }
        }
    }
}
