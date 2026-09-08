# Functions live only for this import job; no System script is installed.
:global mikrowarpNativeInput
:local input $mikrowarpNativeInput
:local action ($input->"action")
:global mikrowarpNativeConfig
:global mikrowarpNativeState
:global mikrowarpNativeRelease
:set mikrowarpNativeRelease @@RELEASE@@
:global mikrowarpNativeLog do={
    :global mikrowarpNativeInput
    :local path ($mikrowarpNativeInput->"log")
    :local old ""
    :local id [/file/find where name=$path]
    :if ([:len $id] > 0) do={ :set old [/file/get $id contents] }
    :if ([:len $old] > 14000) do={ :set old ("# MikroWARP\n" . [:pick $old ([:len $old] - 10000) [:len $old]]) }
    :if ([:len $id] = 0) do={ /file/add name=$path type=file contents=("# MikroWARP\n" . $text . "\n") } else={ /file/set $id contents=($old . $text . "\n") }
}
:global mikrowarpNativeWrite do={
    :local id [/file/find where name=$path]
    :if ([:len $id] = 0) do={ /file/add name=$path type=file contents=$text } else={ /file/set $id contents=$text }
    :if ([/file/get [find where name=$path] contents] != $text) do={ :error "Persistent file readback failed" }
}
:global mikrowarpNativeRead do={
    :local id [/file/find where name=$path]
    :if ([:len $id] = 0) do={ :return "" }
    :return [/file/get $id contents]
}
:global mikrowarpNativeMkdir do={
    :local current ""
    :local remaining $path
    :while ([:len $remaining] > 0) do={
        :local slash [:find $remaining "/"]
        :local part $remaining
        :if ([:typeof $slash] != "nil") do={ :set part [:pick $remaining 0 $slash]; :set remaining [:pick $remaining ($slash + 1) [:len $remaining]] } else={ :set remaining "" }
        :if ($current = "") do={ :set current $part } else={ :set current ($current . "/" . $part) }
        :local id [/file/find where name=$current]
        :if ([:len $id] = 0) do={ /file/add name=$current type=directory } else={
            :local kind [/file/get $id type]
            :if (($kind != "directory") && ($kind != "disk")) do={ :error ("Not a storage directory: " . $current) }
        }
    }
}
# FNV-1a detects torn journal writes; this is not an authentication signature.
:global mikrowarpNativeChecksum do={
    :local hex [:convert $text to=hex]
    :local value 2166136261
    :for i from=0 to=([:len $hex] - 2) step=2 do={ :set value ((($value ^ [:tonum ("0x" . [:pick $hex $i ($i + 2)])]) * 16777619) & 4294967295) }
    :return $value
}
:global mikrowarpNativeBundleCheck do={
    :if ([:len $bundle] = 0) do={ :return true }
    :if ([:typeof $bundle] != "array") do={ :error "Invalid saved release metadata" }
    :foreach key in={"image_id";"sha256"} do={
        :local digest ($bundle->$key)
        :if (([:len $digest] != 64) || !($digest ~ "^[0-9a-f]+\$")) do={ :error "Invalid saved image digest" }
    }
    :foreach key in={"archive_bytes";"logical_bytes"} do={
        :local count ($bundle->$key)
        :if (([:typeof $count] != "num") || ($count < 1) || ($count > 4294967296)) do={ :error "Invalid saved image size" }
    }
    :if (!(($bundle->"revision") ~ "^[A-Za-z0-9._-]+\$") || ([:pick ($bundle->"url") 0 8] != "https://")) do={ :error "Invalid saved release URL or revision" }
    :return true
}
:global mikrowarpNativeRecordCheck do={
    :global mikrowarpNativeBundleCheck
    :if (([:typeof ($record->"sequence")] != "num") || (($record->"sequence") < 0)) do={ :error "Invalid journal sequence" }
    :local phases {"empty";"staging";"quiescing";"switching";"validating-install";"validating";"committing";"complete";"aborting";"aborted"}
    :if ([:typeof [:find $phases ($record->"phase")]] = "nil") do={ :error "Unknown operation phase" }
    :foreach key in={"current";"old";"new"} do={ $mikrowarpNativeBundleCheck bundle=($record->$key) }
    :foreach key in={"snapshot";"restore"} do={
        :local label ($record->$key)
        :if (([:len $label] > 0) && (([:len $label] != 64) || !($label ~ "^[0-9a-f]+\$"))) do={ :error "Invalid state snapshot label" }
    }
    :foreach key in={"previous";"formerPrevious"} do={
        :local previous ($record->$key)
        :if ([:len $previous] > 0) do={
            $mikrowarpNativeBundleCheck bundle=($previous->"bundle")
            :local label ($previous->"snapshot")
            :if (([:len $label] != 64) || !($label ~ "^[0-9a-f]+\$")) do={ :error "Invalid previous state snapshot" }
        }
    }
    :return true
}
:global mikrowarpNativeSave do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeState
    :global mikrowarpNativeChecksum; :global mikrowarpNativeWrite; :global mikrowarpNativeLog; :global mikrowarpNativeMkdir; :global mikrowarpNativeLive; :global mikrowarpNativeRun
    :set ($mikrowarpNativeState->"sequence") (($mikrowarpNativeState->"sequence") + 1)
    :set ($mikrowarpNativeState->"phase") $phase
    :local payload [:serialize to=json value=$mikrowarpNativeState options=json.no-string-conversion]
    :local envelope {"format"="mikrowarp-journal-v1";"payload"=$payload;"checksum"=[$mikrowarpNativeChecksum text=$payload]}
    :local leaf ("operation." . (($mikrowarpNativeState->"sequence") % 2) . ".json")
    $mikrowarpNativeMkdir path=(($mikrowarpNativeConfig->"directory") . "/data/installer")
    $mikrowarpNativeWrite path=(($mikrowarpNativeConfig->"directory") . "/data/installer/" . $leaf) text=[:serialize to=json value=$envelope options=json.no-string-conversion]
    # The existing runtime already provides fsync. Flush the journal before any
    # update cutover, without adding a program or mount to the Standard image.
    :if ([$mikrowarpNativeLive itemName="mikrowarp"]) do={
        $mikrowarpNativeRun itemName="mikrowarp" command=("/usr/local/libexec/mikrowarp-io sync /var/lib/mikrowarp/installer/" . $leaf . " /var/lib/mikrowarp/installer")
    } else={
        # Before first boot there is no runtime fsync helper yet.
        $mikrowarpNativeLog text="Saving progress before continuing (45 seconds)."
        :delay 45s
    }
    $mikrowarpNativeLog text=("Phase: " . $phase)
}
:global mikrowarpNativeComment do={
    :global mikrowarpNativeConfig
    :return ("MikroWARP | " . $purpose . " [" . ($mikrowarpNativeConfig->"owner") . "]")
}
:global mikrowarpNativeQuote do={
    :local result "\""
    :for i from=0 to=([:len $value] - 1) do={
        :local c [:pick $value $i ($i + 1)]
        :if (($c = "\\") || ($c = "\"") || ($c = "\$")) do={ :set result ($result . "\\") }
        :set result ($result . $c)
    }
    :return ($result . "\"")
}
:global mikrowarpNativeEnsure do={
    :global mikrowarpNativeQuote
    :local query [:parse (":return [" . $menu . "/print as-value where " . $selector . "]")]
    :local found [$query]
    :if ([:len $found] > 1) do={ :error ("Ambiguous object: " . $menu) }
    :if ([:len $found] = 1) do={
        :local row [:pick $found 0]
        :foreach key,value in=$properties do={
            :local actual ($row->$key)
            :if ([:typeof $actual] = "bool") do={ :if ($actual) do={ :set actual "yes" } else={ :set actual "no" } }
            :if ([:typeof $actual] = "array") do={ :set actual [:tostr $actual] }
            :if (($key = "src") || ($key = "dst")) do={
                :if ([:pick $actual 0 1] = "/") do={ :set actual [:pick $actual 1 [:len $actual]] }
                :if ([:pick $value 0 1] = "/") do={ :set value [:pick $value 1 [:len $value]] }
            }
            :if (([:tostr $actual] != [:tostr $value]) && !(($key = "src-address") && (([:tostr $actual] . "/32") = $value))) do={ :error ("Existing object differs: " . $menu . " " . $key) }
        }
        :return ($row->".id")
    }
    :local command ($menu . "/add")
    :foreach key,value in=$properties do={ :set command ($command . " " . $key . "=" . [$mikrowarpNativeQuote value=[:tostr $value]]) }
    :local add [:parse $command]; $add
    :local row [:pick [$query] 0]
    :return ($row->".id")
}
:global mikrowarpNativeContainer do={
    :global mikrowarpNativeComment
    :local ids [/container/find where name=$itemName]
    :if ([:len $ids] > 1) do={ :error ("Ambiguous container: " . $itemName) }
    :if ([:len $ids] = 0) do={ :return "" }
    :local id [:pick $ids 0]
    :if ([/container/get $id comment] != [$mikrowarpNativeComment purpose=("Standard " . [:pick ($bundle->"image_id") 0 12])]) do={ :error ("Unowned container: " . $itemName) }
    :return $id
}
:global mikrowarpNativeStopped do={
    :if ([:len [/container/find where name=$itemName]] = 0) do={ :return true }
    :local row [:pick [/container/print as-value where name=$itemName] 0]
    :return (($row->"stopped") || ($row->"download/extract failed"))
}
:global mikrowarpNativeLive do={
    :local rows [/container/print as-value where name=$itemName]
    :if ([:len $rows] != 1) do={ :return false }
    :local row [:pick $rows 0]
    :return (($row->"running") || ($row->"healthy") || ($row->"unhealthy") || ($row->"starting-with-healthcheck"))
}
:global mikrowarpNativeShell do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeInput
    :local id [/container/find where name=$itemName]
    :if ([:len $id] != 1) do={ :error "Container is missing" }
    :local leaf ("router-result-" . ($mikrowarpNativeInput->"token") . ".txt")
    :local resultPath (($mikrowarpNativeConfig->"directory") . "/data/" . $leaf)
    /file/remove [find where name=$resultPath]
    :local script ("(" . $command . ") > /var/lib/mikrowarp/" . $leaf . ".out 2>&1; rc=\$?; { printf '%s\\n' \"\$rc\"; head -c 12000 /var/lib/mikrowarp/" . $leaf . ".out; } > /var/lib/mikrowarp/" . $leaf . "; rm -f /var/lib/mikrowarp/" . $leaf . ".out")
    /container/shell $id cmd=$script
    # File-menu visibility can lag a container's write. Wait for the complete
    # result instead of treating a visibility delay as a failed container boot.
    :local file ""; :local result ""
    :for i from=1 to=20 do={
        :if ([:len $result] = 0) do={
            :set file [/file/find where name=$resultPath]
            :if ([:len $file] > 0) do={ :set result [/file/get $file contents] }
            :if ([:len $result] = 0) do={ :delay 250ms }
        }
    }
    :if ([:len $result] = 0) do={ :error "Container command did not return a result; re-import to resume" }
    /file/remove $file
    :local newline [:find $result "\n"]
    :if ([:typeof $newline] = "nil") do={ :error "Incomplete container result" }
    :local code [:tonum [:pick $result 0 $newline]]
    :if (([:typeof $code] != "num") || ($code < 0) || ($code > 255)) do={ :error "Invalid container command result" }
    :return {"code"=$code;"output"=[:pick $result ($newline + 1) [:len $result]]}
}
:global mikrowarpNativeRun do={
    :global mikrowarpNativeShell
    :local result [$mikrowarpNativeShell itemName=$itemName command=$command]
    :if (($result->"code") != 0) do={ :error ("Container operation failed: " . ($result->"output")) }
    :return ($result->"output")
}
:global mikrowarpNativeReady do={
    :global mikrowarpNativeShell
    :local ready false
    :do { :local result [$mikrowarpNativeShell itemName="mikrowarp" command="/usr/local/sbin/mikrowarp"]; :set ready (($result->"code") = 0) } on-error={}
    :return $ready
}
:global mikrowarpNativeAccept do={
    :global mikrowarpNativeReady; :global mikrowarpNativeRun
    :local ok false
    :local deadline ([:timestamp] + 7m)
    :while ((!$ok) && ([:timestamp] < $deadline)) do={ :set ok [$mikrowarpNativeReady]; :if (!$ok) do={ :delay 5s } }
    :if (!$ok) do={ :error "WARP forwarding did not become healthy within seven minutes" }
    $mikrowarpNativeRun itemName="mikrowarp" command="cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256"
}

# @@OPERATIONS@@

:onerror err in={
    # Parent records this background job before it can change router state.
    :local registered false
    :for i from=1 to=20 do={
        :if (!$registered) do={
            :local lock [:deserialize from=json value=[/file/get [find where name="mikrowarp-operation.lock.json"] contents] options=json.no-string-conversion]
            :if (($lock->"token") != ($input->"token")) do={ :error "Operation lock changed" }
            :set registered (($lock->"job") != "")
            :if (!$registered) do={ :delay 500ms }
        }
    }
    :if (!$registered) do={ :error "Importer disconnected before starting; re-import" }
    # Reboots can leave an operation log after its lock disappeared. Clean only
    # this reserved filename shape with our marker (or an interrupted empty file).
    :foreach f in=[/file/print as-value where name~"^mikrowarp-operation-[0-9a-f]+[.]txt\$"] do={
        :local filename ($f->"name")
        :if (([:len $filename] = 56) && ($filename != ($input->"log"))) do={
            :local content [/file/get ($f->".id") contents]
            :if (([:len $content] = 0) || ([:pick $content 0 [:len "# MikroWARP\n"]] = "# MikroWARP\n")) do={ /file/remove ($f->".id") }
        }
    }
    $mikrowarpNativeLog text="MikroWARP Standard: RouterOS installation and management"
    # @@MAIN@@
    $mikrowarpNativeLog text="RESULT success"
} do={
    :global mikrowarpNativeLog
    $mikrowarpNativeLog text=("Error: " . $err)
    $mikrowarpNativeLog text="RESULT failed; the saved operation can be resumed by re-importing"
}
/system/script/environment/remove [find where name~"^mikrowarpNative"]
