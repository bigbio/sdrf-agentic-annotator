#!/bin/sh
# Refuse `find` rooted at the filesystem root. On a cluster, / includes network and parallel
# filesystems (GPFS, NFS): such a search blocks in uninterruptible I/O for hours and stalls the task.
for arg in "$@"; do
    case "$arg" in
        -H|-L|-P|-D*|-O*) continue ;;
        -*|'!'|'(') break ;;
    esac
    # a starting point: only slashes means the root
    case "$arg" in
        *[!/]*) ;;
        *) echo "find: refusing to search '/' (it can hang for hours on a cluster filesystem). Search under \$SDRF_SKILLS_ROOT (/opt/sdrf-skills), /opt/venv or the task directory instead." >&2; exit 2 ;;
    esac
done
exec /usr/bin/find "$@"
