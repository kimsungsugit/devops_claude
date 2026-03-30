using IniParser;
using IniParser.Model;
using System;
using System.IO;
// Ini Parser 
////https://github.com/rickyah/ini-parser

namespace TResultParser.Lib.Component {
    public class IniFile {

        #region variables 
        // Section 
        public const string SECTION_GLOBAL = "GLOBAL";
        public const string SECTION_QAC = "S_QAC";
        public const string SECTION_VCAST_COMMON = "S_VCAST_COMMON";
        public const string SECTION_VCAST_TC = "S_VCAST_TC";
        public const string SECTION_VCAST_MT = "S_VCAST_MT";
        public const string SECTION_EXCEL = "S_EXCEL";

        // global
        public const string GLB_DATAMODE = "GLB_DATAMODE";

        // qac 
        public const string QAC_PATH = "QAC_PATH";
        public const string QAC_OLDVERSION = "QAC_OLDVERSION";


        // VCAST 
        public const string VCAST_VCASTVER = "VCAST_VERSION";

        // VCAST_TC
        public const string VCAST_TC_TYPE = "VTC_TYPE";
        public const string VCAST_TC_TCPATH = "VTC_TCPATH";
        public const string VCAST_TC_RSLTPATH = "VTC_RSLTPATH";

        public const string VCAST_TC_UNIT = "VTC_UNIT";
        public const string VCAST_TC_ACTONLY = "VTC_ACTONLY";
        public const string VCAST_TC_AUTOSIZE = "VTC_AUTOSIZE";

        // VCAST_MT
        public const string VCAST_MT_UNITID = "VMT_UNITID";
        public const string VCAST_MT_UNIT = "VMT_UNIT";
        public const string VCAST_MT_UNITPATH = "VMT_UNITPATH";
        public const string VCAST_MT_IT = "VMT_IT";
        public const string VCAST_MT_ITPATH = "VMT_ITPATH";
        public const string VCAST_MT_ITAGGPATH = "VMT_ITAGGPATH";
        

        // EXCLE
        public const string XLS_SOURCEPATH = "XLS_SOURCEPATH";
        public const string XLS_SOURCESHEET = "XLS_SOURCESHEET";
        public const string XLS_TARGETPATH = "XLS_TARGETPATH";
        public const string XLS_TARGETSHEET = "XLS_TARGETSHEET";

        private const string INI_FILENAME = "Configuration.ini";
        private IniData m_DataBank { get; set; }
        #endregion

        #region file 
        public IniFile()
        {
            m_DataBank = new IniData();
        }

        public bool open()
        {
            clear();

            string path = getFilePath();
            var parser = new FileIniDataParser();
            if (!File.Exists(path)) {
                parser.WriteFile(path, m_DataBank);
                return false;
            }
            else {
                m_DataBank = parser.ReadFile(path);
            }
            return m_DataBank != null;
        }

        public void save()
        {
            string path = getFilePath();

            var parser = new FileIniDataParser();
            parser.WriteFile(path, m_DataBank);
        }

        public void clear()
        {
            m_DataBank.Sections.Clear();
        }
        #endregion

        #region setValue
        private bool addSection(string section)
        {
            if (string.IsNullOrEmpty(section)) {
                return false;
            }

            var secdata = m_DataBank[section];
            if (secdata == null) {
                m_DataBank.Sections.AddSection(section);
            }
            return true;
        }

        public bool setIntValue(string section, string key, int value)
        {
            if (!addSection(section) || string.IsNullOrEmpty(key)) {
                return false;
            }

            m_DataBank[section][key] = value.ToString();
            return true;
        }

        public bool setBoolValue(string section, string key, bool value)
        {
            if (!addSection(section) || string.IsNullOrEmpty(key)) {
                return false;
            }

            m_DataBank[section][key] = value.ToString();
            return true;
        }

        public bool setStringValue(string section, string key, string value)
        {
            if (!addSection(section) || string.IsNullOrEmpty(key)) {
                return false;
            }

            m_DataBank[section][key] = value;
            return true;
        }

        #endregion

        #region getvalue
        public string getStringValue(string section, string key, string defvalue)
        {
            var secdata = m_DataBank[section];
            if (secdata == null) {
                return defvalue;
            }

            return m_DataBank[section][key];
        }

        public int getIntValue(string section, string key, int defvalue)
        {
            string keydata = getStringValue(section, key, string.Empty);
            if (string.IsNullOrEmpty(keydata)) {
                return defvalue;
            }

            return Convert.ToInt32(keydata);
        }

        public double getDoubleValue(string section, string key, double defvalue)
        {
            string keydata = getStringValue(section, key, string.Empty);
            if (string.IsNullOrEmpty(keydata)) {
                return defvalue;
            }

            return Convert.ToDouble(keydata);
        }

        public bool getBoolValue(string section, string key, bool defvalue)
        {
            string keydata = getStringValue(section, key, string.Empty);
            if (string.IsNullOrEmpty(keydata)) {
                return defvalue;
            }

            return keydata.ToLower() == "true";
        }
        #endregion

        #region Path
        public string getRootDirectory()
        {
            const string CompanyName = "HyunboCorp";
            string m_sProgramName = System.Diagnostics.Process.GetCurrentProcess().ProcessName;
            string sAppDataPath = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string sPath = Path.Combine(sAppDataPath, CompanyName);

            sPath = Path.Combine(sPath, m_sProgramName);
            if (!Directory.Exists(sPath)) {
                Directory.CreateDirectory(sPath);
            }

            return sPath;
        }

        private string getFilePath()
        {
            string path = getRootDirectory();
            return Path.Combine(path, INI_FILENAME);
        }

        #endregion
    }
}
