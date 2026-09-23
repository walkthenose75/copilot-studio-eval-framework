// Power Query (M) starter for the evaluation results repository.
//
// Paste each block into a blank query in Power BI Desktop
// (Home > Transform data > New Source > Blank Query > Advanced Editor).
//
// Set the OrgUrl parameter first:
//   Home > Manage parameters > New parameter
//   Name: OrgUrl   Type: Text   Current value: https://yourorg.crm.dynamics.com
//
// CONNECTOR FUNCTION NAME - CHECK THIS FIRST
// The Dataverse connector function was renamed. Which one resolves depends on
// your Power BI Desktop build:
//     Dataverse.Database(...)           September 2024 and later
//     CommonDataService.Database(...)   earlier builds
// If you get "The name '...' wasn't recognized", switch to the other one - the
// arguments are identical. Both queries below call it through the DataverseDb
// helper, so you change it in ONE place.
//
// Create this as its own blank query named exactly `DataverseDb` FIRST:
//
//     let
//         DataverseDb = (server as text) as table =>
//             CommonDataService.Database(server, [CreateNavigationProperties = false])
//             // ^ swap to Dataverse.Database on Sept 2024+ builds
//     in
//         DataverseDb
//
// OData is shown at the bottom as a fallback where neither function exists.

// ===========================================================================
// Query 1 of 2: EvaluationRun
// ===========================================================================
let
    Source          = DataverseDb(OrgUrl),
    Runs            = Source{[Schema = "dbo", Item = "cse_evaluationrun"]}[Data],
    Selected        = Table.SelectColumns(Runs, {
                          "cse_evaluationrunid", "cse_name", "cse_runid",
                          "cse_agentkey", "cse_agentname", "cse_botid",
                          "cse_environmentid", "cse_environmenttier",
                          "cse_solutionversion", "cse_commitsha",
                          "cse_persona", "cse_suite", "cse_category",
                          "cse_testsetid", "cse_testsetname",
                          "cse_state", "cse_starttime", "cse_endtime",
                          "cse_totaltestcases", "cse_passcount",
                          "cse_failcount", "cse_invalidcount", "cse_passrate",
                          "createdon"
                      }),
    Renamed         = Table.RenameColumns(Selected, {
                          {"cse_evaluationrunid", "RunKey"},
                          {"cse_name",            "Run Name"},
                          {"cse_runid",           "Run ID"},
                          {"cse_agentkey",        "Agent Key"},
                          {"cse_agentname",       "Agent"},
                          {"cse_botid",           "Bot ID"},
                          {"cse_environmentid",   "Environment ID"},
                          {"cse_environmenttier", "Environment"},
                          {"cse_solutionversion", "Solution Version"},
                          {"cse_commitsha",       "Commit"},
                          {"cse_persona",         "Persona"},
                          {"cse_suite",           "Suite"},
                          {"cse_category",        "Category"},
                          {"cse_testsetid",       "Test Set ID"},
                          {"cse_testsetname",     "Test Set"},
                          {"cse_state",           "Run State"},
                          {"cse_starttime",       "Start Time"},
                          {"cse_endtime",         "End Time"},
                          {"cse_totaltestcases",  "Total Test Cases"},
                          {"cse_passcount",       "Pass Count"},
                          {"cse_failcount",       "Fail Count"},
                          {"cse_invalidcount",    "Invalid Count"},
                          {"cse_passrate",        "Pass Rate"},
                          {"createdon",           "Recorded On"}
                      }),
    Typed           = Table.TransformColumnTypes(Renamed, {
                          {"Start Time",   type datetimezone},
                          {"End Time",     type datetimezone},
                          {"Recorded On",  type datetimezone},
                          {"Pass Rate",    type number},
                          {"Pass Count",   Int64.Type},
                          {"Fail Count",   Int64.Type},
                          {"Invalid Count",Int64.Type}
                      }),
    // Duration is the run-health signal that the API does not return directly.
    WithDuration    = Table.AddColumn(Typed, "Duration (min)", each
                          if [Start Time] = null or [End Time] = null then null
                          else Duration.TotalMinutes([End Time] - [Start Time]),
                          type number),
    WithDateKey     = Table.AddColumn(WithDuration, "Run Date", each
                          Date.From([Start Time] ?? [Recorded On]), type date)
in
    WithDateKey


// ===========================================================================
// Query 2 of 2: MetricResult  (the analysis grain)
// ===========================================================================
let
    Source          = DataverseDb(OrgUrl),
    Metrics         = Source{[Schema = "dbo", Item = "cse_metricresult"]}[Data],
    Selected        = Table.SelectColumns(Metrics, {
                          "cse_metricresultid", "cse_evaluationrunid",
                          "cse_testcaseid", "cse_method", "cse_outcome",
                          "cse_rawstatus", "cse_score", "cse_airesultreason",
                          "cse_errorreason", "cse_persona", "cse_suite"
                      }),
    Renamed         = Table.RenameColumns(Selected, {
                          {"cse_metricresultid",  "MetricKey"},
                          {"cse_evaluationrunid", "RunKey"},
                          {"cse_testcaseid",      "Test Case ID"},
                          {"cse_method",          "Test Method"},
                          {"cse_outcome",         "Outcome"},
                          {"cse_rawstatus",       "Raw Status"},
                          {"cse_score",           "Score"},
                          {"cse_airesultreason",  "AI Result Reason"},
                          {"cse_errorreason",     "Error Reason"},
                          {"cse_persona",         "Persona"},
                          {"cse_suite",           "Suite"}
                      }),
    Typed           = Table.TransformColumnTypes(Renamed, {{"Score", type number}}),
    // Trim the reason text so failures group into recognisable clusters.
    ReasonCluster   = Table.AddColumn(Typed, "Failure Cluster", each
                          if [Outcome] <> "fail" then null
                          else Text.Trim(Text.Start([AI Result Reason] ?? [Error Reason] ?? "", 120)),
                          type text)
in
    ReasonCluster


// ===========================================================================
// Model relationship to create in Power BI
// ===========================================================================
//   EvaluationRun[RunKey]  1  ->  *  MetricResult[RunKey]
//   Single direction, single filter. Mark a Date table and relate it to
//   EvaluationRun[Run Date] for time intelligence.
//
// ===========================================================================
// OData fallback (if the Dataverse connector is unavailable)
// ===========================================================================
// let
//     Source = OData.Feed(OrgUrl & "/api/data/v9.2/cse_evaluationruns", null,
//                         [Implementation = "2.0"])
// in
//     Source
