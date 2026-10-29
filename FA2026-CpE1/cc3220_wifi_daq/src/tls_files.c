#include "tls_files.h"

#include <string.h>

#include <ti/drivers/net/wifi/simplelink.h>

#define CA_FILE_MAX_SIZE 4096u
#define CHUNK            64u

static int32_t fileMatches(const char *fileName, const char *pem, uint32_t len)
{
    SlFsFileInfo_t info;
    uint8_t buf[CHUNK];
    uint32_t off;
    int32_t hdl;
    int32_t same = 1;

    if (sl_FsGetInfo((const _u8 *)fileName, 0, &info) < 0) {
        return 0;                       /* no file yet */
    }
    if (info.Len != len) {
        return 0;
    }
    hdl = sl_FsOpen((const _u8 *)fileName, SL_FS_READ, NULL);
    if (hdl < 0) {
        return 0;
    }
    for (off = 0u; (off < len) && same; off += CHUNK) {
        const uint32_t n = ((len - off) < CHUNK) ? (len - off) : CHUNK;
        if ((sl_FsRead(hdl, off, buf, n) != (int32_t)n) || (memcmp(buf, &pem[off], n) != 0)) {
            same = 0;
        }
    }
    (void)sl_FsClose(hdl, NULL, NULL, 0);
    return same;
}

int32_t TlsFiles_installCa(const char *fileName, const char *pem, uint32_t len)
{
    int32_t hdl;
    int32_t ret;

    if ((len == 0u) || (len > CA_FILE_MAX_SIZE)) {
        return -1;
    }
    if (fileMatches(fileName, pem, len)) {
        return 0;
    }
    (void)sl_FsDel((const _u8 *)fileName, 0);    /* an older file may have a smaller max size */
    hdl = sl_FsOpen((const _u8 *)fileName,
                    SL_FS_CREATE | SL_FS_OVERWRITE | SL_FS_CREATE_MAX_SIZE(CA_FILE_MAX_SIZE), NULL);
    if (hdl < 0) {
        return hdl;
    }
    ret = sl_FsWrite(hdl, 0, (_u8 *)pem, len);
    (void)sl_FsClose(hdl, NULL, NULL, 0);
    if (ret != (int32_t)len) {
        return (ret < 0) ? ret : -2;
    }
    return fileMatches(fileName, pem, len) ? 1 : -3;
}

static uint32_t twoDigits(const char *p)
{
    const uint32_t hi = (p[0] == ' ') ? 0u : (uint32_t)(p[0] - '0');
    return hi * 10u + (uint32_t)(p[1] - '0');
}

void TlsFiles_setClockFromBuild(void)
{
    static const char months[] = "JanFebMarAprMayJunJulAugSepOctNovDec";
    const char *date = __DATE__;      /* "Oct 27 2026" */
    const char *time = __TIME__;      /* "14:05:09"    */
    SlDateTime_t dt;
    uint32_t m;

    memset(&dt, 0, sizeof(dt));
    for (m = 0u; m < 12u; ++m) {
        if (strncmp(date, &months[3u * m], 3) == 0) {
            break;
        }
    }
    dt.tm_mon = (m < 12u) ? (m + 1u) : 1u;
    dt.tm_day = twoDigits(&date[4]);
    dt.tm_year = twoDigits(&date[7]) * 100u + twoDigits(&date[9]);
    dt.tm_hour = twoDigits(&time[0]);
    dt.tm_min = twoDigits(&time[3]);
    dt.tm_sec = twoDigits(&time[6]);
    (void)sl_DeviceSet(SL_DEVICE_GENERAL, SL_DEVICE_GENERAL_DATE_TIME,
                       sizeof(SlDateTime_t), (_u8 *)&dt);
}
