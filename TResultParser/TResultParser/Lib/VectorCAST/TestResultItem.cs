using System.Collections.Generic;
using System.Linq;
using VectorReporter.Lib.VectorCAST;

namespace TResultParser.Lib.VectorCAST {
    public class TestResultItem : IVCastItem {

        private static readonly object locker = new object();

        public VCastHeader Header { get; set; }
        public bool IsTestCaseData { get { { return false; } } }

        public int ResultCount { get { lock (locker) { return DicResult.Count; } } }
        public Dictionary<string, TReultValue> DicResult;
        public Dictionary<string, TUserCode> DicUserCode;

        public bool Passed { get; set; }

        public TestResultItem(VCastHeader header)
        {
            clear();
            Header = header;
            DicResult = new Dictionary<string, TReultValue>();
            DicUserCode = new Dictionary<string, TUserCode>();
        }

        public bool addValue(string name, string actual_value, string expeted_value)
        {
            if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(actual_value)) {
                return false;
            }

            lock (locker) {
                if (DicResult == null || DicResult.ContainsKey(name)) {
                    return false;
                }

                DicResult.Add(name, new TReultValue(actual_value, expeted_value));
                return true;
            }
        }

        public bool addUserCode(TUserCode usercode)
        {
            if (usercode == null || !usercode.IsValid) {
                return false;
            }

            lock (locker) {
                if (DicUserCode == null || DicUserCode.ContainsKey(usercode.Name)) {
                    return false;
                }

                DicUserCode.Add(usercode.Name, usercode);
                return true;
            }
        }

        public TReultValue getResultValue(string name)
        {
            if (string.IsNullOrEmpty(name)) {
                return null;
            }

            if (DicResult.ContainsKey(name)) {
                TReultValue item = DicResult[name];
                if (item != null) {
                    return DicResult[name];
                }
            }

            return null;
        }

        public TUserCode getUserCodeValue(string name)
        {
            if (string.IsNullOrEmpty(name)) {
                return null;
            }

            return DicUserCode.ContainsKey(name) ? DicUserCode[name] : null;
        }

        public string getValue(string name)
        {
            TReultValue item = getResultValue(name);
            if (item == null) {
                return string.Empty;
            }

            if (item.Match) {
                return item.ActualValue;
            }

            return  string.Format("{0}({1})", item.ActualValue, item.ExpectedValue);
        }

        public bool match(string name)
        {
            TReultValue item = getResultValue(name);
            return (item == null) ? false: item.Match;
        }

        public List<string> getFieldNameList()
        {
            lock (locker) {
                List<string> list = DicResult.Keys.ToList();

                foreach (var ucode in DicUserCode) {
                    if (list.FindIndex(item => item == ucode.Key) < 0) {
                        list.Add(ucode.Key);
                    }
                }
                return list;

            }
        }

        public void clear()
        {
            if (Header != null) {
                Header.clear();
            }

            if (DicResult != null) {
                DicResult.Clear();
            }

            Passed = false;
        }

        public IVCastItem Clone()
        {
            TestResultItem item = new TestResultItem(Header);

            foreach (var entry in DicResult) {
                item.DicResult.Add(entry.Key, entry.Value);
            }

            foreach (var entry in DicUserCode) {
                item.DicUserCode.Add(entry.Key, entry.Value);
            }

            item.Passed = Passed;
            return item;
        }

        public override string ToString()
        {
            return string.Format("[{0}] Passed : {1}", Header.CompName, Passed);
        }
    }


    #region class TReultValue
    public class TReultValue {
        public string ActualValue { get; set; }
        public string ExpectedValue { get; set; }
        public string Message { get; set; }
        public bool Match { get { return !string.IsNullOrEmpty(ActualValue) && ActualValue == ExpectedValue; } }

        public string ResultText { get { return Match ? ActualValue : string.Format("{0}({1})", ActualValue, ExpectedValue); } }

        public TReultValue(string avalue, string evalue)
        {
            clear();
            ActualValue = avalue.Trim();
            ExpectedValue = evalue.Trim();
        }

        public TReultValue(string avalue, string evalue, string msg)
        {
            clear();
            ActualValue = avalue.Trim();
            ExpectedValue = evalue.Trim();
            Message = msg;
        }

        public void clear()
        {
            ActualValue = string.Empty;
            ExpectedValue = string.Empty;
            Message = string.Empty;
        }
    }
    #endregion

    #region class TUserCode
    public class TUserCode{
        public string Name { get; set; }
        public string Message { get; set; }
        public bool IsValid { get { return !string.IsNullOrEmpty(Name) && !string.IsNullOrEmpty(Message); } }

        // Actual Result 
        public bool IsActualResult { get; set; }
        public bool Match { get; set; }

        public TUserCode(string name, string orgdata)
        {
            clear();
            Name = name.Trim();
            Message = orgdata;
            IsActualResult = false;
        }

        public TUserCode(string name, bool match, string orgdata)
        {
            clear();
            Name = name.Trim();
            Match = match;
            Message = orgdata;
            IsActualResult = true;
        }

        public void clear()
        {
            Name = string.Empty;
            Match = false;
            Message = string.Empty;
            IsActualResult = false;
        }
    }
    #endregion
}
