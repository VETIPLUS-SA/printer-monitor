"""Unit tests for the read-only safety guard (printer_monitor.safety).

These are the tests that matter most in this project: they prove the
extractor is structurally incapable of resetting counters or deleting
accounts on the production printer, no matter what URL it is pointed at.
"""
from printer_monitor.safety import check_request, redact

BASE = "https://192.168.1.59"
LOGIN_URL = f"{BASE}/startwlm/login.cgi"


# -- destructive pages must always be blocked --------------------------------------

def test_reset_counter_page_blocked():
    allowed, reason = check_request(
        "GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_ResetCnt.htm?arg1=0", None
    )
    assert allowed is False
    assert "reset" in reason.lower()


def test_reset_counter_model_js_blocked():
    allowed, _ = check_request(
        "GET",
        f"{BASE}/js/jssrc/model/mngset/jobset/MngSet_JobAcc_ResetCnt.model.htm",
        None,
    )
    assert allowed is False


def test_reset_counter_view_model_js_blocked():
    allowed, _ = check_request(
        "GET",
        f"{BASE}/js/jssrc/view_model/mngset/jobset/MngSet_JobAcc_ResetCnt.view_model.htm",
        None,
    )
    assert allowed is False


def test_delete_account_result_page_blocked():
    allowed, reason = check_request(
        "GET", f"{BASE}/mngset/jobset/MngSet_Acc_DeleteRslt.htm", None
    )
    assert allowed is False
    assert reason


def test_delete_account_result_post_blocked():
    allowed, _ = check_request(
        "POST",
        f"{BASE}/mngset/jobset/MngSet_Acc_DeleteRslt.htm",
        "frmDel=1&cusdoc0=on&cusdoc1=on",
    )
    assert allowed is False


def test_new_account_page_blocked():
    allowed, _ = check_request(
        "GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_NewAcc.htm", None
    )
    assert allowed is False


def test_random_other_mngset_page_blocked():
    allowed, reason = check_request(
        "GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_JobAccModify.htm", None
    )
    assert allowed is False
    assert "allowlist" in reason


# -- login/logout POST -----------------------------------------------------------------

def test_post_auth_login_allowed():
    allowed, _ = check_request(
        "POST", LOGIN_URL, "func=authLogin&arg01_UserName=admin&arg02_Password=secret"
    )
    assert allowed is True


def test_post_auth_logout_allowed():
    allowed, _ = check_request("POST", LOGIN_URL, "func=authLogout")
    assert allowed is True


def test_post_with_other_func_blocked():
    allowed, _ = check_request("POST", LOGIN_URL, "func=authSomethingElse")
    assert allowed is False


def test_post_with_missing_func_blocked():
    allowed, _ = check_request("POST", LOGIN_URL, "arg01_UserName=admin")
    assert allowed is False


def test_post_auth_login_to_another_path_blocked():
    allowed, _ = check_request(
        "POST", f"{BASE}/mngset/jobset/MngSet_JobAcc_JobAccSet.htm", "func=authLogin"
    )
    assert allowed is False


def test_put_blocked():
    allowed, _ = check_request("PUT", LOGIN_URL, "func=authLogin")
    assert allowed is False


def test_delete_method_blocked():
    allowed, _ = check_request("DELETE", f"{BASE}/mngset/jobset/MngSet_JobAcc_JobAccLst.htm", None)
    assert allowed is False


# -- every URL the extractor itself builds must be allowed ------------------------------

def test_home_page_allowed():
    allowed, _ = check_request("GET", f"{BASE}/", None)
    assert allowed is True


def test_startwlm_pages_allowed():
    allowed, _ = check_request("GET", f"{BASE}/startwlm/wlm.htm", None)
    assert allowed is True


def test_account_list_pages_allowed():
    for page_num in (1, 2, 3):
        url = (
            f"{BASE}/mngset/jobset/MngSet_JobAcc_JobAccLst.htm"
            f"?arg1=1&arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7={page_num}&arg8=0&arg9="
        )
        allowed, reason = check_request("GET", url, None)
        assert allowed is True, f"page {page_num} blocked: {reason}"


def test_account_list_model_js_allowed():
    allowed, _ = check_request(
        "GET",
        f"{BASE}/js/jssrc/model/mngset/jobset/MngSet_JobAcc_JobAccLst.model.htm",
        None,
    )
    assert allowed is True


def test_account_set_page_allowed():
    # Referenced by the model JS pathway; part of the read-only allowlist.
    allowed, _ = check_request(
        "GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_JobAccSet.htm", None
    )
    assert allowed is True


_Q = "arg2=0&arg3=&arg4=0&arg5=&arg6=&arg7=1&arg8=0&arg9=&arg10="


def test_print_detail_urls_allowed():
    for arg1 in (0, 2):
        url = f"{BASE}/mngset/jobset/MngSet_JobAcc_EchJobPrnCnt.htm?arg1={arg1}&{_Q}&arg11=5"
        allowed, reason = check_request("GET", url, None)
        assert allowed is True, reason


def test_scan_detail_url_allowed():
    url = f"{BASE}/mngset/jobset/MngSet_JobAcc_EchJobScnCnt.htm?arg1=1&{_Q}&arg11=5"
    allowed, reason = check_request("GET", url, None)
    assert allowed is True, reason


def test_fax_detail_url_allowed():
    url = f"{BASE}/mngset/jobset/MngSet_JobAcc_EchJobFaxCnt.htm?arg1=1&{_Q}&arg11=5"
    allowed, reason = check_request("GET", url, None)
    assert allowed is True, reason


def test_other_account_detail_urls_allowed():
    # private id 101 ("other account") uses the exact same URLs as any
    # other account.
    for name, arg1_values in (
        ("EchJobPrnCnt", (0, 2)),
        ("EchJobScnCnt", (1,)),
        ("EchJobFaxCnt", (1,)),
    ):
        for arg1 in arg1_values:
            url = f"{BASE}/mngset/jobset/MngSet_JobAcc_{name}.htm?arg1={arg1}&{_Q}&arg11=101"
            allowed, reason = check_request("GET", url, None)
            assert allowed is True, reason


def test_device_totals_urls_allowed():
    for name, arg1_values in (
        ("TotPrnCnt", (0, 2)),
        ("TotScnCnt", (1,)),
        ("TotFaxCnt", (1,)),
    ):
        for arg1 in arg1_values:
            url = f"{BASE}/mngset/jobset/MngSet_JobAcc_{name}.htm?arg1={arg1}&{_Q}"
            allowed, reason = check_request("GET", url, None)
            assert allowed is True, reason


def test_detail_model_and_view_model_js_allowed():
    for kind in ("model", "view_model"):
        for name in (
            "MngSet_JobAcc_EchJobPrnCnt",
            "MngSet_JobAcc_EchJobScnCnt",
            "MngSet_JobAcc_EchJobFaxCnt",
            "MngSet_JobAcc_TotPrnCnt",
            "MngSet_JobAcc_TotScnCnt",
            "MngSet_JobAcc_TotFaxCnt",
        ):
            url = f"{BASE}/js/jssrc/{kind}/mngset/jobset/{name}.{kind}.htm"
            allowed, reason = check_request("GET", url, None)
            assert allowed is True, reason


def test_static_assets_allowed():
    for url in (
        f"{BASE}/css/style.css",
        f"{BASE}/js/jssrc/common.js",
        f"{BASE}/strings/en.js",
        f"{BASE}/images/logo.png",
    ):
        allowed, reason = check_request("GET", url, None)
        assert allowed is True, reason


def test_action_named_icons_allowed_but_not_pages_or_posts():
    # The account list shows /images/btn_del_common.png next to the delete form.
    allowed, reason = check_request("GET", f"{BASE}/images/btn_del_common.png", None)
    assert allowed is True, reason
    # The static exemption must never cover pages or non-GET requests.
    for method, url in (
        ("POST", f"{BASE}/images/btn_del_common.png"),
        ("GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_ResetCnt.htm"),
        ("GET", f"{BASE}/mngset/jobset/MngSet_JobAcc_ResetCnt.htm?x=a.png"),
    ):
        allowed, reason = check_request(method, url, None)
        assert allowed is False, (method, url, reason)


# -- redact()---------------------------------------------------------------------------

def test_redact_masks_password():
    body = "func=authLogin&arg01_UserName=admin&arg02_Password=supersecret"
    redacted = redact(body)
    assert "supersecret" not in redacted
    assert "arg02_Password=***" in redacted
    assert "arg01_UserName=admin" in redacted


def test_redact_handles_none_and_empty():
    assert redact(None) == ""
    assert redact("") == ""
