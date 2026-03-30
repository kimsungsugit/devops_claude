using System.Collections.Generic;

namespace VectorReporter.Lib.VectorCAST {
    public class CoverageItem {
        public bool Called {  get { return !(Total == 0 || Count == 0); } }
        public int Count { get; set; }
        public int Total { get; set; }
        public bool Passed {  get { return Total == Count; } }

        public string Percentage { get { return PercentString(); } }
        public string Coverage { get { return CoverageString(); } }
        private string m_Coverage;

        public CoverageItem()
        {
            clear();
        }

        public CoverageItem(string data)
        {
            clear();
            m_Coverage = data;
            if (!string.IsNullOrEmpty(data)) {

                List<string> list = VIMLib.splitString(data, new char[] { '/', '(' });
                if (list.Count >= 2) {
                    Count = VIMLib.strToInt(list[0]);
                    Total = VIMLib.strToInt(list[1]);
                }
            }
        }

        private string CoverageString()
        {
            if (!string.IsNullOrEmpty(m_Coverage)) {
                return m_Coverage;
            }

            return Total == 0 ? "0 / 0 (0 %)" : string.Format("{0}/{1}({2} %)", Count, Total, Count * 100 / Total);
        }

        private string PercentString()
        {
            return Total == 0 ? "-" : string.Format("{0} %", Count * 100 / Total);
        }

        public void clear()
        {
            Count = 0;
            Total = 0;
            m_Coverage = string.Empty;
        }
    }
}
