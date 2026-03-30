namespace TResultParser.GUI.Controls {
    partial class UCXlsList {
        /// <summary> 
        /// Required designer variable.
        /// </summary>
        private System.ComponentModel.IContainer components = null;

        /// <summary> 
        /// Clean up any resources being used.
        /// </summary>
        /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null)) {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Component Designer generated code

        /// <summary> 
        /// Required method for Designer support - do not modify 
        /// the contents of this method with the code editor.
        /// </summary>
        private void InitializeComponent()
        {
            System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(UCXlsList));
            this.fgridXlsDiff = new C1.Win.C1FlexGrid.C1FlexGrid();
            ((System.ComponentModel.ISupportInitialize)(this.fgridXlsDiff)).BeginInit();
            this.SuspendLayout();
            // 
            // fgridXlsDiff
            // 
            this.fgridXlsDiff.AllowEditing = false;
            this.fgridXlsDiff.ColumnInfo = "4,1,0,0,0,100,Columns:";
            this.fgridXlsDiff.Dock = System.Windows.Forms.DockStyle.Fill;
            this.fgridXlsDiff.Location = new System.Drawing.Point(0, 0);
            this.fgridXlsDiff.Name = "fgridXlsDiff";
            this.fgridXlsDiff.Rows.Count = 5;
            this.fgridXlsDiff.Rows.DefaultSize = 20;
            this.fgridXlsDiff.Size = new System.Drawing.Size(829, 751);
            this.fgridXlsDiff.StyleInfo = resources.GetString("fgridXlsDiff.StyleInfo");
            this.fgridXlsDiff.TabIndex = 0;
            // 
            // UCXlsList
            // 
            this.AutoScaleDimensions = new System.Drawing.SizeF(7F, 12F);
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.Controls.Add(this.fgridXlsDiff);
            this.Name = "UCXlsList";
            this.Size = new System.Drawing.Size(829, 751);
            this.Load += new System.EventHandler(this.UCXlsList_Load);
            ((System.ComponentModel.ISupportInitialize)(this.fgridXlsDiff)).EndInit();
            this.ResumeLayout(false);

        }

        #endregion

        private C1.Win.C1FlexGrid.C1FlexGrid fgridXlsDiff;
    }
}
