namespace TResultParser.Lib.VectorCAST {

    #region enum
    public enum VCastItemMode {
        TestCase = 0,
        TestResult,
        TestReport,

        None,
    }
    #endregion

    public interface IVCastItem {
        bool IsTestCaseData { get; }
        VCastHeader Header{get;set;}
        void clear();

        IVCastItem Clone();
    }
}
