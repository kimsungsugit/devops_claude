ECHO OFF
FOR /R %%X IN (*.RESX) DO (
	SortRESX "%%X"
	ECHO ">"
)