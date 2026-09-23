#!/usr/bin/env python3
"""Create the evaluation results repository in Dataverse.

Creates a publisher, a solution, the tables, their columns and the
relationship between them - all via the documented Dataverse Web API:
  https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/create-update-entity-definitions-using-web-api

Why a script and not a pre-built solution .zip
----------------------------------------------
A table's customisation prefix comes from the solution publisher and CANNOT be
changed after creation. A pre-baked .zip would hard-code someone else's prefix
into your environment permanently. This script takes the prefix as input, so
you own your own naming from the first run - and once the tables exist you can
export a real, versioned, environment-native solution:

    pac solution export --name CopilotStudioEvaluationFramework --managed false

Usage:
    python provision_schema.py --url https://yourorg.crm.dynamics.com
    python provision_schema.py --url ... --prefix acme --dry-run

Idempotent: existing tables and columns are detected and skipped, so it is
safe to re-run after adding a column to schema.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval_runner.auth import TokenProvider  # noqa: E402

API = "/api/data/v9.2"
LCID = 1033


def label(text: str) -> dict:
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.Label",
        "LocalizedLabels": [{
            "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
            "Label": text,
            "LanguageCode": LCID,
        }],
    }


def required_level(value: str = "None") -> dict:
    return {
        "Value": value,
        "CanBeChanged": True,
        "ManagedPropertyLogicalName": "canmodifyrequirementlevelsettings",
    }


def build_attribute(prefix: str, spec: dict, is_primary: bool = False) -> dict:
    """Build an AttributeMetadata payload for a column spec.

    Deliberately limited to String, Memo, Integer, DateTime and Decimal.
    Choice/Boolean columns need option-set metadata; text keeps the schema
    portable and the values readable in Power BI without a join.
    """
    schema_name = f"{prefix}_{spec['name']}"
    display = spec.get("displayName", spec["name"])
    kind = spec.get("type", "String")

    common = {
        "SchemaName": schema_name,
        "DisplayName": label(display),
        "RequiredLevel": required_level("ApplicationRequired" if is_primary else "None"),
    }
    if spec.get("description"):
        common["Description"] = label(spec["description"])

    if kind == "String":
        return {
            **common,
            "@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata",
            "AttributeType": "String",
            "AttributeTypeName": {"Value": "StringType"},
            "MaxLength": int(spec.get("maxLength", 100)),
            "FormatName": {"Value": "Text"},
            **({"IsPrimaryName": True} if is_primary else {}),
        }
    if kind == "Memo":
        return {
            **common,
            "@odata.type": "Microsoft.Dynamics.CRM.MemoAttributeMetadata",
            "AttributeType": "Memo",
            "AttributeTypeName": {"Value": "MemoType"},
            "MaxLength": int(spec.get("maxLength", 2000)),
            "Format": "TextArea",
        }
    if kind == "Integer":
        return {
            **common,
            "@odata.type": "Microsoft.Dynamics.CRM.IntegerAttributeMetadata",
            "AttributeType": "Integer",
            "AttributeTypeName": {"Value": "IntegerType"},
            "MinValue": int(spec.get("minValue", -2147483648)),
            "MaxValue": int(spec.get("maxValue", 2147483647)),
            "Format": "None",
        }
    if kind == "DateTime":
        return {
            **common,
            "@odata.type": "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata",
            "AttributeType": "DateTime",
            "AttributeTypeName": {"Value": "DateTimeType"},
            "Format": "DateAndTime",
            "DateTimeBehavior": {"Value": "UserLocal"},
        }
    if kind == "Decimal":
        return {
            **common,
            "@odata.type": "Microsoft.Dynamics.CRM.DecimalAttributeMetadata",
            "AttributeType": "Decimal",
            "AttributeTypeName": {"Value": "DecimalType"},
            "Precision": int(spec.get("precision", 2)),
            "MinValue": float(spec.get("minValue", -100000000000)),
            "MaxValue": float(spec.get("maxValue", 100000000000)),
        }
    raise ValueError(f"Unsupported column type '{kind}' for '{spec['name']}'.")


class Provisioner:
    def __init__(self, org_url: str, tokens: TokenProvider, prefix: str,
                 solution_name: str, dry_run: bool = False) -> None:
        self.org_url = org_url.rstrip("/")
        self.tokens = tokens
        self.prefix = prefix
        self.solution_name = solution_name
        self.dry_run = dry_run
        self.session = requests.Session()

    def _headers(self, in_solution: bool = False) -> dict:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Consistency": "Strong",
            **self.tokens.header(),
        }
        if in_solution:
            headers["MSCRM.SolutionUniqueName"] = self.solution_name
        return headers

    def _post(self, path: str, body: dict, in_solution: bool = False) -> requests.Response | None:
        url = f"{self.org_url}{API}/{path}"
        if self.dry_run:
            print(f"    [dry-run] POST {path}")
            print(f"    {json.dumps(body)[:240]}...")
            return None
        response = self.session.post(url, json=body, headers=self._headers(in_solution), timeout=180)
        if not response.ok:
            raise SystemExit(
                f"\nERROR: POST {path} failed ({response.status_code}).\n{response.text[:900]}\n"
            )
        return response

    def _get(self, path: str) -> dict:
        if self.dry_run:
            return {}
        response = self.session.get(
            f"{self.org_url}{API}/{path}", headers=self._headers(), timeout=120
        )
        if response.status_code == 404:
            return {}
        if not response.ok:
            raise SystemExit(f"\nERROR: GET {path} failed ({response.status_code}).\n{response.text[:600]}\n")
        return response.json()

    # -- steps ---------------------------------------------------------

    def ensure_publisher(self, spec: dict) -> str | None:
        existing = self._get(
            f"publishers?$select=publisherid&$filter=uniquename eq '{spec['uniqueName']}'"
        )
        if existing.get("value"):
            print(f"  = publisher '{spec['uniqueName']}' already exists")
            return existing["value"][0]["publisherid"]
        print(f"  + publisher '{spec['uniqueName']}' (prefix '{self.prefix}')")
        response = self._post("publishers", {
            "friendlyname": spec["friendlyName"],
            "uniquename": spec["uniqueName"],
            "description": spec.get("description", ""),
            "customizationprefix": self.prefix,
            "customizationoptionvalueprefix": int(spec.get("customizationOptionValuePrefix", 63200)),
        })
        if response is None:
            return None
        return response.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")

    def ensure_solution(self, spec: dict, publisher_id: str | None) -> None:
        existing = self._get(
            f"solutions?$select=solutionid&$filter=uniquename eq '{self.solution_name}'"
        )
        if existing.get("value"):
            print(f"  = solution '{self.solution_name}' already exists")
            return
        print(f"  + solution '{self.solution_name}'")
        self._post("solutions", {
            "friendlyname": spec["friendlyName"],
            "uniquename": self.solution_name,
            "description": spec.get("description", ""),
            "version": spec.get("version", "1.0.0.0"),
            "publisherid@odata.bind": f"/publishers({publisher_id})",
        })

    def table_exists(self, logical_name: str) -> str | None:
        result = self._get(
            f"EntityDefinitions(LogicalName='{logical_name}')?$select=MetadataId"
        )
        return result.get("MetadataId")

    def ensure_table(self, table: dict) -> None:
        logical = f"{self.prefix}_{table['name']}"
        metadata_id = self.table_exists(logical)
        if metadata_id:
            print(f"  = table '{logical}' already exists")
            self.ensure_columns(logical, table)
            return

        primary = table["primaryName"]
        print(f"  + table '{logical}'")
        body = {
            "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
            "SchemaName": f"{self.prefix}_{table['name']}",
            "DisplayName": label(table["displayName"]),
            "DisplayCollectionName": label(table["displayCollectionName"]),
            "Description": label(table.get("description", "")),
            "OwnershipType": "UserOwned",
            "IsActivity": False,
            "HasActivities": False,
            "HasNotes": False,
            "Attributes": [build_attribute(self.prefix, primary, is_primary=True)],
        }
        self._post("EntityDefinitions", body, in_solution=True)
        self.ensure_columns(logical, table, assume_new=True)

    def ensure_columns(self, logical: str, table: dict, assume_new: bool = False) -> None:
        existing: set[str] = set()
        if not assume_new and not self.dry_run:
            result = self._get(
                f"EntityDefinitions(LogicalName='{logical}')/Attributes?$select=LogicalName"
            )
            existing = {a["LogicalName"] for a in result.get("value", [])}

        for spec in table.get("columns", []):
            column_logical = f"{self.prefix}_{spec['name']}"
            if column_logical in existing:
                continue
            print(f"      + column '{column_logical}' ({spec.get('type', 'String')})")
            self._post(
                f"EntityDefinitions(LogicalName='{logical}')/Attributes",
                build_attribute(self.prefix, spec),
                in_solution=True,
            )

    def ensure_relationship(self, rel: dict) -> None:
        schema_name = f"{self.prefix}_{rel['schemaName']}"
        referenced = f"{self.prefix}_{rel['referencedTable']}"
        referencing = f"{self.prefix}_{rel['referencingTable']}"

        if not self.dry_run:
            existing = self._get(
                "RelationshipDefinitions/Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata"
                f"?$select=SchemaName&$filter=SchemaName eq '{schema_name}'"
            )
            if existing.get("value"):
                print(f"  = relationship '{schema_name}' already exists")
                return

        print(f"  + relationship '{schema_name}' ({referenced} 1:N {referencing})")
        self._post(
            "RelationshipDefinitions",
            {
                "@odata.type": "Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata",
                "SchemaName": schema_name,
                "ReferencedEntity": referenced,
                "ReferencingEntity": referencing,
                "CascadeConfiguration": {
                    "Assign": "NoCascade",
                    "Delete": "Cascade",
                    "Merge": "NoCascade",
                    "Reparent": "NoCascade",
                    "Share": "NoCascade",
                    "Unshare": "NoCascade",
                },
                "AssociatedMenuConfiguration": {
                    "Behavior": "UseCollectionName",
                    "Group": "Details",
                    "Order": 10000,
                    "IsCustomizable": True,
                },
                "Lookup": {
                    "@odata.type": "Microsoft.Dynamics.CRM.LookupAttributeMetadata",
                    "AttributeType": "Lookup",
                    "AttributeTypeName": {"Value": "LookupType"},
                    "SchemaName": f"{self.prefix}_{rel['lookupName']}",
                    "DisplayName": label(rel["lookupDisplayName"]),
                    "RequiredLevel": required_level("None"),
                },
            },
            in_solution=True,
        )

    def publish(self) -> None:
        print("  * publishing customisations")
        self._post("PublishAllXml", {})


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the Dataverse results repository.")
    parser.add_argument("--url", required=True, help="https://yourorg.crm.dynamics.com")
    parser.add_argument("--schema", default=os.path.join(os.path.dirname(__file__), "schema.json"))
    parser.add_argument("--prefix", help="Publisher customisation prefix (overrides schema.json).")
    parser.add_argument("--solution", help="Solution unique name (overrides schema.json).")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads, change nothing.")
    args = parser.parse_args()

    with open(args.schema, "r", encoding="utf-8") as handle:
        schema = json.load(handle)

    prefix = (args.prefix or schema["publisher"]["customizationPrefix"]).strip().lower()
    if not (2 <= len(prefix) <= 8) or not prefix.isalnum() or not prefix[0].isalpha():
        raise SystemExit(
            "ERROR: prefix must be 2-8 alphanumeric characters starting with a letter."
        )
    if prefix.startswith("mscrm"):
        raise SystemExit("ERROR: prefix cannot start with 'mscrm'.")

    solution_name = args.solution or schema["solution"]["uniqueName"]
    org_url = args.url.rstrip("/")

    tokens = TokenProvider(
        mode=os.environ.get("DATAVERSE_AUTH_MODE")
        or ("client_secret" if os.environ.get("CLIENT_SECRET") else "device_code"),
        tenant_id=os.environ.get("TENANT_ID", ""),
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scope=f"{org_url}/.default",
        resource=org_url,
    )

    print(f"\nProvisioning into {org_url}")
    print(f"  prefix   : {prefix}")
    print(f"  solution : {solution_name}")
    print(f"  dry run  : {args.dry_run}\n")

    provisioner = Provisioner(org_url, tokens, prefix, solution_name, args.dry_run)
    publisher_id = provisioner.ensure_publisher(schema["publisher"])
    provisioner.ensure_solution(schema["solution"], publisher_id)
    for table in schema["tables"]:
        provisioner.ensure_table(table)
    for relationship in schema.get("relationships", []):
        provisioner.ensure_relationship(relationship)
    if not args.dry_run:
        provisioner.publish()

    print(f"\nDone. Set these in .env:\n  DATAVERSE_URL={org_url}\n  DATAVERSE_PREFIX={prefix}\n")
    print("Export as a versioned solution with:")
    print(f"  pac solution export --name {solution_name} --managed false\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
