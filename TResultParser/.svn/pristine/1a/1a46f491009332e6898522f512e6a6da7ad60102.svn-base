namespace TResultParser.Lib.VectorCAST {
    public class VCastHeader {

        // TC Configuartion
        public string CompName { get { return m_CompName; } }
        private string m_CompName;
        public string UnitName { get { return m_UnitName; } }
        private string m_UnitName;

        public string Description { get; set; } // Requirement Note

        // FileName
        public string FileName { get { return m_FileName; } }
        private string m_FileName;

        // TC Name
        public string TCFullName { get { return m_TCFullName; } }
        private string m_TCFullName;
        public string TCName { get { return m_TCName; } }
        private string m_TCName;
        public int TCIndex { get { return m_TCIndex; } }
        public int m_TCIndex;

        public VCastHeader(string compname, string unitname, string tcname, string filename)
        {
            clear();

            m_CompName = compname;
            m_UnitName = unitname;

            m_TCFullName = tcname;
            m_FileName = filename;

            if (!string.IsNullOrEmpty(m_TCFullName)) {
                int pos = m_TCFullName.LastIndexOf(".");
                if (pos >= 0) {
                    m_TCName = m_TCFullName.Substring(0, pos);
                    string index = m_TCFullName.Substring(pos + 1, m_TCFullName.Length - pos - 1);
                    if (!string.IsNullOrEmpty(index)) {
                        int.TryParse(index, out m_TCIndex);
                    }
                }
            }
        }

        public void clear()
        {
            m_CompName = string.Empty;
            m_UnitName = string.Empty;

            Description = string.Empty;

            m_TCFullName = string.Empty;
            m_TCName = string.Empty;
            m_TCIndex = -1;

            m_FileName = string.Empty;
        }
    }
}
