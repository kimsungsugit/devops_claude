namespace VectorReporter.Lib.VectorCAST {
    public enum MatricsType {
        // Unit Test 
        Statement,
        // Integration Test
        Functions,
        None,
    }

    public interface IMatrixPrototype {
        MatricsType MType { get; }
        string UnitID { get; set; } // For Reprot

        string ID { get;}
        string UnitName { get; set; }
        string SubProgram { get; set; }
        int Complexity { get; set; }
        bool IsValid { get; set; }

        void clear();
    }
}
