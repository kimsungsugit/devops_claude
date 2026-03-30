using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace TResultParser {
    static class Program {
        /// <summary>
        /// The main entry point for the application.
        /// </summary>
        private const string DueDate = "2025/11/30";

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            // Time Limit
            if (!IsInDueDate()) {
                MessageBox.Show("This program is out of date!!\r\nPlease use latest version.", "Message", MessageBoxButtons.OK);
                return;
            }

            Application.Run(new FormMain(args));
        }

        private static bool IsInDueDate()
        {
            DateTime dtDueDate = DateTime.Parse(DueDate);
            return (DateTime.Today <= dtDueDate);
        }

    }

}
