import os
import shutil
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

CHROME_USER_DATA = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome"
)
PROFILE_NAME = "Profile 11"


def safe_remove(path: Path) -> None:
    if not path.exists():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
    except Exception:
        pass


def copy_profile_to_temp() -> str:
    src_root = Path(CHROME_USER_DATA)
    src_profile = src_root / PROFILE_NAME
    src_local_state = src_root / "Local State"

    if not src_root.exists():
        raise FileNotFoundError(f"Chrome user data dir not found: {src_root}")

    if not src_profile.exists():
        raise FileNotFoundError(f"Chrome profile not found: {src_profile}")

    temp_root = Path(tempfile.mkdtemp(prefix="pw_chrome_clone_"))
    dst_profile = temp_root / PROFILE_NAME

    # Copy Local State so Chrome knows about profile metadata
    if src_local_state.exists():
        shutil.copy2(src_local_state, temp_root / "Local State")

    # Copy only the selected profile, while skipping unstable/runtime/cache files
    shutil.copytree(
        src_profile,
        dst_profile,
        ignore=shutil.ignore_patterns(
            "Singleton*",
            "LOCK",
            "lockfile",
            "*.log",
            "Crashpad",
            "ShaderCache",
            "GrShaderCache",
            "GraphiteDawnCache",
            "Code Cache",
            "GPUCache",
            "DawnCache",
            "blob_storage",
        ),
        dirs_exist_ok=True,
    )

    # Extra cleanup in cloned copy
    for name in [
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "LOCK",
        "lockfile",
        "Lockfile",
    ]:
        safe_remove(temp_root / name)
        safe_remove(dst_profile / name)

    return str(temp_root)


# def main() -> None:
#     cloned_user_data_dir = copy_profile_to_temp()
#     print(f"Using cloned Chrome session at: {cloned_user_data_dir}")

#     try:
#         with sync_playwright() as p:
#             context = p.chromium.launch_persistent_context(
#                 user_data_dir=cloned_user_data_dir,
#                 channel="chrome",
#                 headless=False,
#                args=[
#         f"--profile-directory={PROFILE_NAME}",
#         "--disable-blink-features=AutomationControlled",
#         "--disable-infobars",
#         "--excludeSwitches=enable-automation",
#     ],
#     ignore_default_args=["--enable-automation", "--enable-blink-features=AutomationControlled"],
#             )

#             page = context.new_page()
#             page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
#             page.wait_for_timeout(8000)

#             print("Title:", page.title())
#             print("Current URL:", page.url)

#             context.close()

#     finally:
#         # Uncomment this if you want the temp copy deleted after every run
#         # shutil.rmtree(cloned_user_data_dir, ignore_errors=True)
#         pass


def main() -> None:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_USER_DATA,
            channel="chrome",
            headless=False,
            args=[
                f"--profile-directory={PROFILE_NAME}",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--excludeSwitches=enable-automation",
            ],
            ignore_default_args=["--enable-automation", "--enable-blink-features=AutomationControlled"],
        )

        page = context.new_page()
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        print("Title:", page.title())
        print("Current URL:", page.url)

        context.close()


if __name__ == "__main__":
    main()




# import os
# import shutil
# import tempfile
# from pathlib import Path
# from playwright.sync_api import sync_playwright

# CHROME_USER_DATA = os.path.expanduser(
#     "~/Library/Application Support/Google/Chrome"
# )
# PROFILE_NAME = "Profile 11"


# def safe_remove(path: Path) -> None:
#     if not path.exists():
#         return
#     try:
#         if path.is_dir():
#             shutil.rmtree(path, ignore_errors=True)
#         else:
#             path.unlink()
#     except Exception:
#         pass


# def copy_profile_to_temp() -> str:
#     src_root = Path(CHROME_USER_DATA)
#     src_profile = src_root / PROFILE_NAME
#     src_local_state = src_root / "Local State"

#     if not src_root.exists():
#         raise FileNotFoundError(f"Chrome user data dir not found: {src_root}")

#     if not src_profile.exists():
#         raise FileNotFoundError(f"Chrome profile not found: {src_profile}")

#     temp_root = Path(tempfile.mkdtemp(prefix="pw_chrome_clone_"))
#     dst_profile = temp_root / PROFILE_NAME

#     if src_local_state.exists():
#         shutil.copy2(src_local_state, temp_root / "Local State")

#     # Copy full profile — all cookies, sessions, storage
#     shutil.copytree(
#         src_profile,
#         dst_profile,
#         dirs_exist_ok=True,
#     )

#     # Only remove singleton/lock files that would block Chrome from starting
#     for name in [
#         "SingletonLock",
#         "SingletonCookie",
#         "SingletonSocket",
#         "LOCK",
#         "lockfile",
#         "Lockfile",
#     ]:
#         safe_remove(temp_root / name)
#         safe_remove(dst_profile / name)

#     return str(temp_root)


# def main() -> None:
#     cloned_user_data_dir = copy_profile_to_temp()
#     print(f"Using cloned Chrome session at: {cloned_user_data_dir}")

#     try:
#         with sync_playwright() as p:
#             context = p.chromium.launch_persistent_context(
#                 user_data_dir=cloned_user_data_dir,
#                 channel="chrome",
#                 headless=False,
#                 args=[
#                     f"--profile-directory={PROFILE_NAME}",
#                     "--disable-blink-features=AutomationControlled",
#                     "--disable-infobars",
#                     "--excludeSwitches=enable-automation",
#                 ],
#                 ignore_default_args=["--enable-automation", "--enable-blink-features=AutomationControlled"],
#             )

#             page = context.new_page()
#             page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
#             page.wait_for_timeout(8000)

#             print("Title:", page.title())
#             print("Current URL:", page.url)

#             context.close()

#     finally:
#         pass


# if __name__ == "__main__":
#     main()





https://acornvillages.com/jobs
https://www.epilepsy.org.uk/about/vacancies
https://abbeyfield-bristol.co.uk/join-our-team/
https://www.bcom.ac.uk/about-us/work-with-us/








No jobs found - manual review required
https://abbeyfield-bristol.co.uk/join-our-team/
No valid navigation target found.
There are jobs listed
No jobs found - manual review required
https://acornvillages.com/jobs
No valid navigation target found.
There are jobs listed
No jobs found - manual review required
https://www.epilepsy.org.uk/about/vacancies#row-fc-4
No valid navigation target found.
There is a job listed for Initial Contact Assessor
No jobs found - manual review required
https://www.bcom.ac.uk/about-us/work-with-us/
No valid navigation target found.
There are jobs listed
No jobs found - manual review required
https://www.aberdeenfoyer.com/vacancies
No valid navigation target found.
There are no jobs listed
No jobs found - manual review required
https://aldridgeeducation.org/Vacancies
Error scraping jobs
There are no jobs listed
No jobs found - manual review required
https://www.brb.org.uk/jobs
No valid navigation target found.
There is a job listed (not sure if this was there originally)

Finding irrelevant caree





# find wrong career url 
https://www.bishopluffa.org.uk/home/vacancies/

# llm mistake, it didn't see apply url so it put as uncertain which is wrong.
https://www.ashiana.org.uk/specialist-advocate/



