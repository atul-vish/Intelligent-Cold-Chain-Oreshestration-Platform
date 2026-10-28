/*
    Intelligent Cold-Chain Orchestration Platform
    SQL Server security and semantic-view setup

    SECURITY:
    - This tracked file contains no real password.
    - Run in SQLCMD mode and supply SQL_AGENT_PASSWORD through a secure,
      local-only SQLCMD variable workflow.
    - Never commit a variables file containing the password.
    - SQLCMD replaces $(SQL_AGENT_PASSWORD) before SQL Server executes this
      script. Do not paste a real password into this tracked source file.

    Expected SQLCMD variable: SQL_AGENT_PASSWORD
    Execute against the target application database as an administrator.
*/

SET NOCOUNT ON;
GO

/* 1. Create the semantic schema if it does not exist. */
IF SCHEMA_ID(N'FDE_VIEWS') IS NULL
BEGIN
    EXEC(N'CREATE SCHEMA FDE_VIEWS AUTHORIZATION dbo;');
END;
GO

/* 2. Create or update the semantic view. */
CREATE OR ALTER VIEW FDE_VIEWS.VW_ACTIVE_FLEET
AS
SELECT
    TS_UTC AS [Timestamp],
    V_LAT AS [Latitude],
    V_LON AS [Longitude],
    CAST(IOT_TEMP_VAL_C AS FLOAT) AS [Current_Temperature_C],
    CGO_COND_CD AS [Cargo_Condition_Code],
    RISK_CLS_TXT AS [Risk_Classification],
    DELAY_PROB_DEC AS [Delay_Probability],
    PRT_CNG_LVL AS [Port_Congestion_Level],
    RT_RSK_IDX AS [Route_Risk_Index]
FROM dbo.TBL_SC_FLEET_HIST_RAW;
GO

/*
  3. Create the server login if it does not already exist.
  Run this script in SQLCMD mode and provide SQL_AGENT_PASSWORD using your
  secure local secret workflow. Never hardcode a real password here.
*/
IF SUSER_ID(N'USR_FDE_RO') IS NULL
BEGIN
    CREATE LOGIN [USR_FDE_RO]
        WITH PASSWORD = N'$(SQL_AGENT_PASSWORD)',
             CHECK_POLICY = ON,
             CHECK_EXPIRATION = ON;
END;
GO

/* 4. Create the database user if it does not exist. */
IF DATABASE_PRINCIPAL_ID(N'USR_FDE_RO') IS NULL
BEGIN
    CREATE USER [USR_FDE_RO] FOR LOGIN [USR_FDE_RO];
END;
GO

/* 5. Grant least-privilege access to the semantic view only. */
GRANT SELECT ON OBJECT::FDE_VIEWS.VW_ACTIVE_FLEET TO [USR_FDE_RO];
GO

DENY SELECT, INSERT, UPDATE, DELETE
    ON OBJECT::dbo.TBL_SC_FLEET_HIST_RAW TO [USR_FDE_RO];
GO

DENY INSERT, UPDATE, DELETE, ALTER, CONTROL
    ON SCHEMA::dbo TO [USR_FDE_RO];
GO

/*
  Notes:
  - Do not add this login to db_owner, db_datareader, or db_datawriter.
  - If the login already exists, this script does not change its password.
  - Validate effective permissions by testing with a separate connection
    authenticated as USR_FDE_RO.
*/
