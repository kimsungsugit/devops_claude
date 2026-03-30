using System.Collections.Generic;

namespace TResultParser.Lib.VectorCAST {
    public class TestItem<T>{

        public bool ResultMode { get { return m_ResultMode; } }
        private bool m_ResultMode;
        public string TestName { get; set; }
        public Dictionary<int, T> DicData { get; set; }

        public bool Passed { get; set; }

        public TestItem(bool resultmode, string name)
        {
            m_ResultMode = resultmode;
            TestName = name;
            DicData = new Dictionary<int, T>();
            Passed = true;
        }

        public T getData(int index)
        {
            if (DicData.ContainsKey(index)) {
                return DicData[index];
            }

            return default(T);
        }

        public void clear()
        {
            TestName = string.Empty;
            DicData.Clear();

            Passed = true;
        }

        public TestItem<T> Clone()
        {
            TestItem<T> item = new TestItem<T>(this.ResultMode, this.TestName);
            item.Passed = this.Passed;

            foreach (var entry in this.DicData) {
                item.DicData.Add(entry.Key, entry.Value);
            }
            return item;
        }
    }
}
