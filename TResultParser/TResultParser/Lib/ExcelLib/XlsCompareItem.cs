using System.IO;

namespace TResultParser.Lib.ExcelLib {
    public class XlsCompareItem {

        private const string XLSX_EXTENSION = ".xlsx";
        private const string XLSM_EXTENSION = ".xlsm";
        public string PathSource { get; set; }
        public string PathTarget { get; set; }

        public int SheetSource { get; set; }
        public int SheetTarget { get; set; }
        public bool Valid { get { return doesValid(); } }

        public XlsCompareItem()
        {
            clear();
        }

        private bool doesValid()
        {
            if (string.IsNullOrEmpty(PathSource) || !File.Exists(PathSource) ||
                string.IsNullOrEmpty(PathTarget) || !File.Exists(PathTarget)) {
                return false;
            }

            if (SheetSource <= 0 || SheetTarget <= 0) {
                return false;
            }

            string source_ext = Path.GetExtension(PathSource).ToLower();
            string target_ext = Path.GetExtension(PathTarget).ToLower();
            return (source_ext == XLSX_EXTENSION && target_ext == XLSX_EXTENSION) || (source_ext == XLSM_EXTENSION && target_ext == XLSM_EXTENSION);
        }

        public XlsCompareItem(string path1, string path2, int sht1, int sht2)
        {
            clear();

            PathSource = path1;
            PathTarget = path2;

            SheetSource = sht1;
            SheetTarget = sht2;
        }

        public void clear()
        {
            PathSource = string.Empty;
            PathTarget = string.Empty;

            SheetSource = 1;
            SheetTarget = 1;
        }
    }
}
