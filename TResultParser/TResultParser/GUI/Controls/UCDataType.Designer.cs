namespace TResultParser.GUI.Controls {
    partial class UCDataType {
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
            System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(UCDataType));
            this.fgridDataMode = new C1.Win.C1FlexGrid.C1FlexGrid();
            ((System.ComponentModel.ISupportInitialize)(this.fgridDataMode)).BeginInit();
            this.SuspendLayout();
            // 
            // fgridDataMode
            // 
            this.fgridDataMode.AllowEditing = false;
            this.fgridDataMode.ColumnInfo = "1,0,0,0,0,100,Columns:";
            this.fgridDataMode.Dock = System.Windows.Forms.DockStyle.Fill;
            this.fgridDataMode.Location = new System.Drawing.Point(0, 0);
            this.fgridDataMode.Name = "fgridDataMode";
            this.fgridDataMode.Rows.Count = 5;
            this.fgridDataMode.Rows.DefaultSize = 20;
            this.fgridDataMode.SelectionMode = C1.Win.C1FlexGrid.SelectionModeEnum.Row;
            this.fgridDataMode.Size = new System.Drawing.Size(244, 597);
            this.fgridDataMode.StyleInfo = resources.GetString("fgridDataMode.StyleInfo");
            this.fgridDataMode.TabIndex = 1;
            this.fgridDataMode.Tree.Column = 0;
            this.fgridDataMode.MouseClick += new System.Windows.Forms.MouseEventHandler(this.fgridDataMode_MouseClick);
            // 
            // UCDataType
            // 
            this.AutoScaleDimensions = new System.Drawing.SizeF(7F, 12F);
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.Controls.Add(this.fgridDataMode);
            this.Name = "UCDataType";
            this.Size = new System.Drawing.Size(244, 597);
            this.Load += new System.EventHandler(this.UCDataType_Load);
            this.SizeChanged += new System.EventHandler(this.UCDataType_SizeChanged);
            ((System.ComponentModel.ISupportInitialize)(this.fgridDataMode)).EndInit();
            this.ResumeLayout(false);

        }

        #endregion

        private C1.Win.C1FlexGrid.C1FlexGrid fgridDataMode;
    }
}
