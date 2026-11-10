<#
  Read-only schema inspection for the Pulse database. Runs only SELECTs on catalog views
  (plus optional TOP 5 sample rows). Uses the SQL client built into Windows PowerShell 5.1,
  so nothing needs installing.

  Entra ID (Ascendion account):  az login   then
      .\tools\inspect_db.ps1 -Server <name>.database.windows.net -Database <db>
  SQL login:  $env:PULSE_SQL_PASSWORD = '...'   then
      .\tools\inspect_db.ps1 -Server ... -Database ... -Auth SqlLogin -User <user>

  Output: a markdown report (default tools\db_inspection.md). NOT TESTED YET - written before DB access.
#>
param(
    [Parameter(Mandatory = $true)] [string]$Server,
    [Parameter(Mandatory = $true)] [string]$Database,
    [ValidateSet('AzCli', 'SqlLogin')] [string]$Auth = 'AzCli',
    [string]$User,
    [switch]$Samples,
    [string]$OutFile = (Join-Path $PSScriptRoot 'db_inspection.md')
)
$ErrorActionPreference = 'Stop'

$cs = "Server=tcp:$Server,1433;Database=$Database;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;"
$conn = New-Object System.Data.SqlClient.SqlConnection
if ($Auth -eq 'AzCli') {
    $token = az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv
    if (-not $token) { throw 'No token. Run az login with your Ascendion account first.' }
    $conn.ConnectionString = $cs
    $conn.AccessToken = $token
} else {
    if (-not $User -or -not $env:PULSE_SQL_PASSWORD) { throw 'Give -User and set $env:PULSE_SQL_PASSWORD.' }
    $conn.ConnectionString = $cs + "User ID=$User;Password=$($env:PULSE_SQL_PASSWORD);"
}
$conn.Open()

function Q([string]$sql) {
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $sql; $cmd.CommandTimeout = 60
    $dt = New-Object System.Data.DataTable
    [void](New-Object System.Data.SqlClient.SqlDataAdapter $cmd).Fill($dt)
    return , $dt
}

function MdTable($dt) {
    if ($dt.Rows.Count -eq 0) { return "_none_`n" }
    $cols = @($dt.Columns | ForEach-Object { $_.ColumnName })
    $s = '| ' + ($cols -join ' | ') + " |`n|" + (($cols | ForEach-Object { '---' }) -join '|') + "|`n"
    foreach ($r in $dt.Rows) {
        $cells = $cols | ForEach-Object { ("$($r[$_])" -replace '\|', '\|' -replace "`r?`n", ' ') }
        $s += '| ' + ($cells -join ' | ') + " |`n"
    }
    return $s
}

$sections = [ordered]@{
    'Tables and row counts' = @"
SELECT s.name AS SchemaName, t.name AS TableName, SUM(p.rows) AS [Rows]
FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
GROUP BY s.name, t.name ORDER BY s.name, t.name;
"@
    'Columns' = @"
SELECT c.TABLE_SCHEMA AS SchemaName, c.TABLE_NAME AS TableName, c.COLUMN_NAME AS ColumnName,
       c.DATA_TYPE + ISNULL('(' + CASE WHEN c.CHARACTER_MAXIMUM_LENGTH = -1 THEN 'MAX'
            ELSE CAST(c.CHARACTER_MAXIMUM_LENGTH AS VARCHAR(10)) END + ')', '') AS DataType,
       c.IS_NULLABLE AS Nullable,
       COLUMNPROPERTY(OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)), c.COLUMN_NAME, 'IsIdentity') AS IsIdentity,
       c.COLUMN_DEFAULT AS DefaultValue
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES tb ON tb.TABLE_SCHEMA = c.TABLE_SCHEMA AND tb.TABLE_NAME = c.TABLE_NAME AND tb.TABLE_TYPE = 'BASE TABLE'
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION;
"@
    'Primary and unique keys' = @"
SELECT s.name AS SchemaName, t.name AS TableName, k.name AS KeyName, k.type_desc AS KeyType,
       STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS Columns
FROM sys.key_constraints k
JOIN sys.tables t ON t.object_id = k.parent_object_id JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.index_columns ic ON ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
GROUP BY s.name, t.name, k.name, k.type_desc ORDER BY s.name, t.name;
"@
    'Foreign keys' = @"
SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id) + '.' + OBJECT_NAME(fk.parent_object_id) AS ChildTable,
       cp.name AS ChildColumn,
       OBJECT_SCHEMA_NAME(fk.referenced_object_id) + '.' + OBJECT_NAME(fk.referenced_object_id) AS ParentTable,
       cr.name AS ParentColumn, fk.name AS FkName, fk.delete_referential_action_desc AS OnDelete
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id
ORDER BY ChildTable;
"@
    'Check constraints' = @"
SELECT OBJECT_SCHEMA_NAME(parent_object_id) + '.' + OBJECT_NAME(parent_object_id) AS TableName,
       name AS ConstraintName, definition AS Definition
FROM sys.check_constraints ORDER BY TableName;
"@
    'Views, procedures, functions' = @"
SELECT SCHEMA_NAME(schema_id) AS SchemaName, name AS ObjectName, type_desc AS ObjectType, modify_date AS Modified
FROM sys.objects WHERE type IN ('V', 'P', 'FN', 'IF', 'TF', 'TR') AND is_ms_shipped = 0
ORDER BY type_desc, name;
"@
}

$report = "# DB inspection: $Database on $Server`n_Generated $(Get-Date -Format 'yyyy-MM-dd HH:mm')_`n`n"
foreach ($title in $sections.Keys) {
    $report += "## $title`n`n" + (MdTable (Q $sections[$title])) + "`n"
}

if ($Samples) {
    $report += "## Sample rows (TOP 5)`n`n"
    foreach ($r in (Q 'SELECT s.name AS S, t.name AS T FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id ORDER BY s.name, t.name;').Rows) {
        $report += "### $($r.S).$($r.T)`n`n" + (MdTable (Q "SELECT TOP 5 * FROM [$($r.S)].[$($r.T)];")) + "`n"
    }
}

$conn.Close()
$report | Out-File -FilePath $OutFile -Encoding utf8
Write-Output "Wrote $OutFile"
