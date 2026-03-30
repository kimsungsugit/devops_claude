using System.Collections.Generic;
using System.Linq;

namespace TResultParser.Lib.VectorCAST {
    public class TestCaseItem : IVCastItem {
        public enum TCDataMode {
            Input,
            ExpectedRslt,
        }

        private static readonly object locker = new object();

        public VCastHeader Header { get; set; }
        public bool IsTestCaseData { get { { return true; } } }

        public int InputCount {  get { lock (locker) { return DicInput.Count; } } }
        public Dictionary<string, string> DicInput;
        
        public int ExpResultCount { get { lock (locker) { return DicExpRestult.Count; } } }
        public Dictionary<string, ExpectResultItem> DicExpRestult;

        public TestCaseItem(VCastHeader header)
        {
            clear();
            Header = header;
            
            DicInput = new Dictionary<string, string>();
            DicExpRestult = new Dictionary<string, ExpectResultItem>();
        }

        public void clear()
        {
            if (Header != null) {
                Header.clear();
            }

            if (DicInput != null) {
                DicInput.Clear();
            }
            if (DicExpRestult != null) {
                DicExpRestult.Clear();
            }
        }

        public List<string> getFieldNameList(TCDataMode datamode)
        {
            lock (locker) {

                if (datamode == TCDataMode.Input) {
                    return DicInput.Keys.ToList();
                }
                else {
                    return DicExpRestult.Keys.ToList();
                }
            }
        }

        public ExpectResultItem getExpectedResultItem(string name)
        {
            if (string.IsNullOrEmpty(name)) {
                return null;
            }

            return DicExpRestult.ContainsKey(name) ? DicExpRestult[name] : null;
        }

        public string getInputValue(string name)
        {
            if (string.IsNullOrEmpty(name)) {
                return string.Empty;
            }

            return DicInput.ContainsKey(name) ? DicInput[name] : string.Empty;
        }
 
        public bool addValue(bool input, string name, string value)
        {
            if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(value)) {
                return false;
            }

            lock (locker) {
                if (input) {
                    if (DicInput.ContainsKey(name)) {
                        return false;
                    }

                    DicInput.Add(name, value);
                }
                else {
                    if (DicExpRestult.ContainsKey(name)) {
                        return false;
                    }

                    DicExpRestult.Add(name, new ExpectResultItem(name, value, false));
                }

                return true;
            }
        }

        public bool addUserCode(string name, string usercodemessage)
        {
            if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(usercodemessage)) {
                return false;
            }

            lock (locker) {
                if (DicExpRestult.ContainsKey(name)) {
                    return false;
                }

                DicExpRestult.Add(name, new ExpectResultItem(name, usercodemessage, true));
                return true;
            }
        }

        public IVCastItem Clone()
        {
            TestCaseItem item = new TestCaseItem(Header);

            foreach (var entry in DicInput) {
                item.DicInput.Add(entry.Key, entry.Value);
            }

            foreach (var entry in DicExpRestult) {
                item.DicExpRestult.Add(entry.Key, entry.Value);
            }

            return item;
        }
    }


    #region class
    public class ExpectResultItem {
        public string Name { get; set; }
        public string Result { get; set; }
        public string UserCodeMsg { get; set; }
        public bool IsUserCode {  get { return string.IsNullOrEmpty(Result) && !string.IsNullOrEmpty(UserCodeMsg); } }

        public string Mesaage { get { return IsUserCode ? UserCodeMsg : Result; } }

        public ExpectResultItem(string name, string message, bool usercode)
        {
            clear();
            Name = name;

            if (usercode) {
                UserCodeMsg = message;
            }
            else {
                Result = message;
            }
        }

        public void clear()
        {
            Name = string.Empty;
            Result = string.Empty;
            UserCodeMsg = string.Empty;
        }

    }
    #endregion
}
