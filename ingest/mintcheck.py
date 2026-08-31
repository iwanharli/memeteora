"""What the mint account says about a token - things no price API reports.

A pool can look perfect on every metric and still be untouchable because of
how its token is configured. These are read straight from the mint account,
batched 100 at a time.
"""
import base64, json, struct, time, urllib.request

RPC = "https://api.mainnet-beta.solana.com"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

EXT_NAMES = {
    1: "TransferFeeConfig", 2: "TransferFeeAmount", 3: "MintCloseAuthority",
    4: "ConfidentialTransfer", 6: "DefaultAccountState", 7: "ImmutableOwner",
    8: "MemoTransfer", 9: "NonTransferable", 10: "InterestBearing",
    11: "CpiGuard", 12: "PermanentDelegate", 14: "TransferHook",
    16: "MetadataPointer", 17: "TokenMetadata", 18: "GroupPointer",
    19: "GroupMemberPointer", 20: "TokenGroup", 21: "TokenGroupMember",
}
# extensions that can take value out of an LP position or freeze it in place
HOSTILE = {
    "TransferFeeConfig": "every transfer is taxed, which silently eats LP returns",
    "NonTransferable": "the token cannot be moved at all",
    "PermanentDelegate": "a delegate can seize tokens from any account",
    "TransferHook": "an arbitrary program runs on transfer and can block it",
    "DefaultAccountState": "new accounts can default to frozen",
    "MintCloseAuthority": "the mint can be closed",
}


def _rpc(method, params, tries=3):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    for i in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body.encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _parse(data_b64, owner):
    """SPL Mint is 82 bytes: COption authority(4+32), supply u64, decimals u8,
    is_initialized bool, COption freeze(4+32). Token-2022 appends TLV
    extensions after a 165-byte pad and a 1-byte account type."""
    d = base64.b64decode(data_b64)
    if len(d) < 82:
        return None
    out = {
        "token_program": owner,
        "mint_auth_active": struct.unpack_from("<I", d, 0)[0] == 1,
        "freeze_auth_active": struct.unpack_from("<I", d, 46)[0] == 1,
        "extensions": [],
        "transfer_fee_bps": None,
    }
    if owner != TOKEN_2022 or len(d) < 166:
        return out

    o = 166
    while o + 4 <= len(d):
        et, ln = struct.unpack_from("<HH", d, o)
        o += 4
        if et == 0 or o + ln > len(d):
            break
        name = EXT_NAMES.get(et, f"unknown({et})")
        out["extensions"].append(name)
        if et == 1 and ln >= 104:
            # TransferFeeConfig: 32 authority + 32 withdraw + 8 withheld,
            # then older and newer TransferFee { epoch u64, max u64, bps u16 }
            out["transfer_fee_bps"] = struct.unpack_from("<H", d, o + 32 + 32 + 8 + 8 + 8)[0]
        o += ln
    return out


def check(mints):
    """{mint: {...}} for every mint that exists on chain."""
    out = {}
    for i in range(0, len(mints), 100):
        chunk = mints[i:i + 100]
        res = _rpc("getMultipleAccounts", [chunk, {"encoding": "base64"}])["result"]["value"]
        for mint, v in zip(chunk, res):
            if not v:
                continue
            parsed = _parse(v["data"][0], v["owner"])
            if parsed:
                out[mint] = parsed
        time.sleep(0.1)
    return out


def hostile_extensions(extensions):
    return [e for e in (extensions or []) if e in HOSTILE]
