:global mikrowarpNativeSpace do={
    :global mikrowarpNativeConfig
    :local path ($mikrowarpNativeConfig->"directory")
    :local free [/system/resource/get free-hdd-space]
    :foreach disk in=[/disk/print as-value] do={
        :local mount ($disk->"mount-point")
        :if (([:len $mount] > 0) && (($path = $mount) || ([:pick $path 0 ([:len $mount] + 1)] = ($mount . "/")))) do={ :set free ($disk->"free") }
    }
    :return $free
}
:global mikrowarpNativeDownload do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeMkdir; :global mikrowarpNativeSpace; :global mikrowarpNativeLog
    :local base ($mikrowarpNativeConfig->"directory")
    :local path ($base . "/archives/" . ($bundle->"sha256") . ".tar.gz")
    :local existing [/file/find where name=$path]
    :local need ((2 * ($bundle->"logical_bytes")) + 268435456)
    :if ([:len $existing] > 0) do={
        :if ([/file/get $existing size] != ($bundle->"archive_bytes")) do={ :error "Saved image has the wrong size; it has been retained for inspection" }
        :if ([$mikrowarpNativeSpace] < $need) do={ :error ("Insufficient staging space: need " . $need . " free bytes with the archive already present") }
        :return $path
    }
    :set need ($need + ($bundle->"archive_bytes"))
    :if ([$mikrowarpNativeSpace] < $need) do={ :error ("Insufficient staging space: need " . $need . " free bytes") }
    $mikrowarpNativeMkdir path=($base . "/archives")
    :local partial ($path . ".partial")
    /file/remove [find where name=$partial]
    $mikrowarpNativeLog text=("Downloading " . ($bundle->"revision") . " (" . ($bundle->"archive_bytes") . " bytes)")
    :onerror err in={
        /tool/fetch url=($bundle->"url") dst-path=$partial check-certificate=yes http-max-redirect-count=5 idle-timeout=30s duration=30m
        :if ([/file/get [find where name=$partial] size] != ($bundle->"archive_bytes")) do={ :error "Download size does not match release metadata" }
        /file/set [find where name=$partial] name=$path
    } do={ /file/remove [find where name=$partial]; :error ("Download failed; re-import to retry. " . $err) }
    :return $path
}
:global mikrowarpNativeImport do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeContainer; :global mikrowarpNativeMkdir; :global mikrowarpNativeComment; :global mikrowarpNativeLog; :global mikrowarpNativeLive; :global mikrowarpNativeRemove
    :local id [$mikrowarpNativeContainer itemName=$itemName bundle=$bundle]
    :local created false
    :if (($id != "") && ![$mikrowarpNativeLive itemName=$itemName]) do={
        # After a reboot, an extraction may look complete while its last writes
        # were lost. Rebuild a stopped candidate from the retained archive.
        :local extracting true
        :for i from=1 to=180 do={
            :if ($extracting) do={
                :local row [:pick [/container/print as-value where name=$itemName] 0]
                :set extracting (($row->"extracting") || ($row->"downloading") || ($row->"downloading/extracting"))
                :if ($extracting) do={ :delay 5s }
            }
        }
        :if ($extracting) do={ :error "Extraction is still running; re-import when it finishes" }
        $mikrowarpNativeRemove itemName=$itemName bundle=$bundle
        :set id ""
    }
    :if ($id = "") do={
        :set created true
        $mikrowarpNativeRemove itemName=$itemName bundle=$bundle
        :local release (($mikrowarpNativeConfig->"directory") . "/releases/" . [:pick ($bundle->"image_id") 0 16])
        $mikrowarpNativeMkdir path=$release
        $mikrowarpNativeLog text=("Importing stopped image: " . $itemName)
        /container/add name=$itemName file=$archive interface=mikrowarp-veth root-dir=($release . "/root") layer-dir=($release . "/layers") envlists=mikrowarp mountlists=mikrowarp dns=1.1.1.1 user=0:0 logging=yes start-on-boot=no restart-policy=always restart-interval=10s comment=[$mikrowarpNativeComment purpose=("Standard " . [:pick ($bundle->"image_id") 0 12])]
    }
    :local done false
    :for i from=1 to=180 do={
        :if (!$done) do={
            :set id [$mikrowarpNativeContainer itemName=$itemName bundle=$bundle]
            :local row [:pick [/container/print as-value where name=$itemName] 0]
            :if (($row->"error") || ($row->"failed") || ($row->"download/extract failed")) do={ :error "Container image extraction failed" }
            :if (!(($row->"extracting") || ($row->"downloading") || ($row->"downloading/extracting"))) do={
                :if ([/container/get $id image-id] != ($bundle->"image_id")) do={ :error "Imported image ID does not match the pinned release" }
                :set done true
            } else={ :delay 5s }
        }
    }
    :if (!$done) do={ :error "Image extraction is still pending; re-import to resume" }
    :if ($created) do={
        $mikrowarpNativeLog text="Allowing extracted image writes to settle before cutover (45 seconds)."
        :delay 45s
    }
    :return $id
}
:global mikrowarpNativeStop do={
    :global mikrowarpNativeContainer; :global mikrowarpNativeStopped
    :local id [$mikrowarpNativeContainer itemName=$itemName bundle=$bundle]
    :if ($id = "") do={ :return true }
    :if (![$mikrowarpNativeStopped itemName=$itemName]) do={ /container/stop $id }
    :local stopped false
    :for i from=1 to=60 do={ :if (!$stopped) do={ :set stopped [$mikrowarpNativeStopped itemName=$itemName]; :if (!$stopped) do={ :delay 2s } } }
    :if (!$stopped) do={ :error ("Container did not stop: " . $itemName) }
    # Also cancel a restart already queued by a candidate that exits immediately.
    :if ([/container/get $id start-on-boot] || ([/container/get $id restart-policy] != "no")) do={ /container/set $id start-on-boot=no restart-policy=no }
}
:global mikrowarpNativeStart do={
    :global mikrowarpNativeContainer; :global mikrowarpNativeStopped; :global mikrowarpNativeStop; :global mikrowarpNativeShell
    :local id [$mikrowarpNativeContainer itemName=$itemName bundle=$bundle]
    :if ($id = "") do={ :error "Missing container during start" }
    :if ((![/container/get $id start-on-boot]) || ([/container/get $id restart-policy] != "always")) do={
        :if (![$mikrowarpNativeStopped itemName=$itemName]) do={ $mikrowarpNativeStop itemName=$itemName bundle=$bundle }
        /container/set $id start-on-boot=yes restart-policy=always restart-interval=10s
    }
    :if ([$mikrowarpNativeStopped itemName=$itemName]) do={ /container/start $id }
    :local available false
    :local lastError "Container boot is not initialized"
    :local deadline ([:timestamp] + 2m)
    :while ((!$available) && ([:timestamp] < $deadline)) do={
        :onerror err in={ :local r [$mikrowarpNativeShell itemName=$itemName command="test -r /run/mikrowarp/runtime.env"]; :set available (($r->"code") = 0) } do={ :set lastError $err }
        :if (!$available) do={ :delay 2s }
    }
    :if (!$available) do={ :error ("Container command interface did not become ready: " . $lastError) }
}
:global mikrowarpNativeRename do={
    :global mikrowarpNativeContainer; :global mikrowarpNativeStopped
    :if ([:len [/container/find where name=$target]] > 0) do={ :error "Container rename target is occupied" }
    :local id [$mikrowarpNativeContainer itemName=$source bundle=$bundle]
    :if (($id = "") || (![$mikrowarpNativeStopped itemName=$source])) do={ :error "Rename requires a stopped owned container" }
    /container/set $id name=$target
}
:global mikrowarpNativeRemove do={
    :global mikrowarpNativeContainer; :global mikrowarpNativeStopped; :global mikrowarpNativeConfig
    :local id [$mikrowarpNativeContainer itemName=$itemName bundle=$bundle]
    :if ($id != "") do={
        :if (![$mikrowarpNativeStopped itemName=$itemName]) do={ :error "Refusing to remove a running container" }
        /container/remove $id
        :local removed false
        :for i from=1 to=90 do={ :if (!$removed) do={ :set removed ([:len [/container/find where name=$itemName]] = 0); :if (!$removed) do={ :delay 2s } } }
        :if (!$removed) do={ :error "Container removal is still pending" }
    }
    :local release (($mikrowarpNativeConfig->"directory") . "/releases/" . [:pick ($bundle->"image_id") 0 16])
    # Layer/root cleanup must never affect another container referencing this release.
    :local used false
    :foreach c in=[/container/print as-value] do={ :if ([:typeof [:find ($c->"root-dir") ($release . "/")]] != "nil") do={ :set used true } }
    :foreach layer in=[/container/layers/print as-value] do={
        :local directory [:tostr ($layer->"layer-dir")]
        :if (([:len ($layer->"containers")] > 0) && ([:typeof [:find ($directory . "/") ($release . "/")]] != "nil")) do={ :set used true }
    }
    :if (!$used) do={
        # RouterOS may release the container row before finishing directory GC.
        :for i from=1 to=60 do={
            :local files [/file/find where name=$release]
            :if ([:len $files] > 0) do={ :do { /file/remove $files } on-error={}; :if ([:len [/file/find where name=$release]] > 0) do={ :delay 2s } }
        }
        :if ([:len [/file/find where name=$release]] > 0) do={ :error "Release directory cleanup is still pending; re-import to resume" }
    }
}
:global mikrowarpNativeCommit do={
    :global mikrowarpNativeConfig; :global mikrowarpNativeState; :global mikrowarpNativeSave; :global mikrowarpNativeRemove; :global mikrowarpNativeRun
    :local old ($mikrowarpNativeState->"old"); :local new ($mikrowarpNativeState->"new")
    :local former ($mikrowarpNativeState->"formerPrevious")
    :set ($mikrowarpNativeState->"current") $new
    :set ($mikrowarpNativeState->"previous") {"bundle"=$old;"snapshot"=($mikrowarpNativeState->"snapshot")}
    $mikrowarpNativeSave phase="committing"
    $mikrowarpNativeRemove itemName="mikrowarp-old" bundle=$old
    :if ([:len ($former->"snapshot")] > 0) do={
        :local obsolete ($former->"bundle")
        :if ((($obsolete->"sha256") != ($old->"sha256")) && (($obsolete->"sha256") != ($new->"sha256"))) do={ /file/remove [find where name=(($mikrowarpNativeConfig->"directory") . "/archives/" . ($obsolete->"sha256") . ".tar.gz")] }
        :local label ($former->"snapshot")
        :if (([:len $label] = 64) && ($label ~ "^[0-9a-f]+\$") && ($label != ($mikrowarpNativeState->"snapshot"))) do={ $mikrowarpNativeRun itemName="mikrowarp" command=("rm -f /var/lib/mikrowarp/recovery/" . $label . ".tar /var/lib/mikrowarp/recovery/" . $label . ".tar.sha256") }
    }
    $mikrowarpNativeSave phase="complete"
}
:global mikrowarpNativeAbort do={
    :global mikrowarpNativeState; :global mikrowarpNativeConfig; :global mikrowarpNativeSave; :global mikrowarpNativeWrite
    :global mikrowarpNativeStop; :global mikrowarpNativeRemove; :global mikrowarpNativeRename; :global mikrowarpNativeStart; :global mikrowarpNativeImport; :global mikrowarpNativeRun; :global mikrowarpNativeLog
    :if (($mikrowarpNativeState->"phase") = "committing") do={ :error "Commit has started; re-import to finish before selecting rollback" }
    :local old ($mikrowarpNativeState->"old"); :local new ($mikrowarpNativeState->"new")
    :local base ($mikrowarpNativeConfig->"directory")
    $mikrowarpNativeSave phase="aborting"
    :if (($mikrowarpNativeState->"kind") = "install") do={
        $mikrowarpNativeStop itemName="mikrowarp" bundle=$new
        $mikrowarpNativeSave phase="aborted"
        $mikrowarpNativeLog text="Installation stopped. Owned files and registration are retained; re-import to retry."
        :return true
    }
    :if ($mikrowarpNativeState->"snapshotCreated") do={ $mikrowarpNativeWrite path=($base . "/data/maintenance.lock") text="administrator_operation" }
    :local id [/container/find where name="mikrowarp"]
    :if ([:len $id] > 0) do={
        :if ([/container/get $id image-id] = ($new->"image_id")) do={ $mikrowarpNativeStop itemName="mikrowarp" bundle=$new; $mikrowarpNativeRemove itemName="mikrowarp" bundle=$new }
    }
    :if ([:len [/container/find where name="mikrowarp"]] = 0) do={
        :if ([:len [/container/find where name="mikrowarp-old"]] > 0) do={ $mikrowarpNativeRename source="mikrowarp-old" target="mikrowarp" bundle=$old } else={ $mikrowarpNativeImport itemName="mikrowarp" bundle=$old archive=($base . "/archives/" . ($old->"sha256") . ".tar.gz") }
    }
    $mikrowarpNativeStart itemName="mikrowarp" bundle=$old
    :if ($mikrowarpNativeState->"snapshotCreated") do={
        $mikrowarpNativeRun itemName="mikrowarp" command="/usr/local/sbin/mikrowarp maintenance begin"
        $mikrowarpNativeRun itemName="mikrowarp" command=("/usr/local/sbin/mikrowarp maintenance restore " . ($mikrowarpNativeState->"snapshot"))
    }
    $mikrowarpNativeRun itemName="mikrowarp" command="/usr/local/sbin/mikrowarp maintenance resume"
    $mikrowarpNativeStop itemName="mikrowarp-next" bundle=$new
    $mikrowarpNativeRemove itemName="mikrowarp-next" bundle=$new
    :set ($mikrowarpNativeState->"current") $old
    :set ($mikrowarpNativeState->"previous") ($mikrowarpNativeState->"formerPrevious")
    :local previousBundle (($mikrowarpNativeState->"previous")->"bundle")
    :if ((($new->"sha256") != ($old->"sha256")) && (($new->"sha256") != ($previousBundle->"sha256"))) do={ /file/remove [find where name=($base . "/archives/" . ($new->"sha256") . ".tar.gz")] }
    :if ($mikrowarpNativeState->"snapshotCreated") do={
        :local label ($mikrowarpNativeState->"snapshot")
        $mikrowarpNativeRun itemName="mikrowarp" command=("rm -f /var/lib/mikrowarp/recovery/" . $label . ".tar /var/lib/mikrowarp/recovery/" . $label . ".tar.sha256")
    }
    $mikrowarpNativeSave phase="aborted"
    $mikrowarpNativeLog text="Previous image and matching state restored; ordinary WARP recovery is active."
}
:global mikrowarpNativeResume do={
    :global mikrowarpNativeState; :global mikrowarpNativeConfig; :global mikrowarpNativeSave; :global mikrowarpNativeDownload
    :global mikrowarpNativeImport; :global mikrowarpNativeStart; :global mikrowarpNativeRun; :global mikrowarpNativeStop; :global mikrowarpNativeRename; :global mikrowarpNativeAccept; :global mikrowarpNativeCommit; :global mikrowarpNativeAbort; :global mikrowarpNativeLog
    :if (($mikrowarpNativeState->"phase") = "aborting") do={ $mikrowarpNativeAbort; :return true }
    :if (($mikrowarpNativeState->"phase") = "committing") do={ $mikrowarpNativeCommit; :return true }
    :local old ($mikrowarpNativeState->"old"); :local new ($mikrowarpNativeState->"new")
    :local archive [$mikrowarpNativeDownload bundle=$new]
    :if (($mikrowarpNativeState->"kind") = "install") do={
        $mikrowarpNativeImport itemName="mikrowarp" bundle=$new archive=$archive
        $mikrowarpNativeStart itemName="mikrowarp" bundle=$new
        $mikrowarpNativeSave phase="validating-install"
        $mikrowarpNativeLog text="Waiting for forwarded WARP HTTPS and UDP DNS health."
        $mikrowarpNativeAccept
        :set ($mikrowarpNativeState->"current") $new
        $mikrowarpNativeSave phase="complete"
        :return true
    }
    :local current [/container/find where name="mikrowarp"]
    :if ([:len $current] > 0) do={
        :if ([/container/get $current image-id] = ($old->"image_id")) do={
            $mikrowarpNativeImport itemName="mikrowarp-next" bundle=$new archive=$archive
            $mikrowarpNativeSave phase="quiescing"
            $mikrowarpNativeStart itemName="mikrowarp" bundle=$old
            $mikrowarpNativeRun itemName="mikrowarp" command="/usr/local/sbin/mikrowarp maintenance begin"
            $mikrowarpNativeRun itemName="mikrowarp" command=("/usr/local/sbin/mikrowarp maintenance snapshot " . ($mikrowarpNativeState->"snapshot"))
            :set ($mikrowarpNativeState->"snapshotCreated") true
            $mikrowarpNativeSave phase="switching"
            $mikrowarpNativeStop itemName="mikrowarp" bundle=$old
            $mikrowarpNativeRename source="mikrowarp" target="mikrowarp-old" bundle=$old
        }
    }
    :if ([:len [/container/find where name="mikrowarp"]] = 0) do={ $mikrowarpNativeRename source="mikrowarp-next" target="mikrowarp" bundle=$new }
    :onerror err in={
        $mikrowarpNativeStart itemName="mikrowarp" bundle=$new
        :if (([:len ($mikrowarpNativeState->"restore")] > 0) && (($mikrowarpNativeState->"phase") != "validating")) do={
            $mikrowarpNativeRun itemName="mikrowarp" command="/usr/local/sbin/mikrowarp maintenance begin"
            $mikrowarpNativeRun itemName="mikrowarp" command=("/usr/local/sbin/mikrowarp maintenance restore " . ($mikrowarpNativeState->"restore"))
        }
        $mikrowarpNativeSave phase="validating"
        $mikrowarpNativeRun itemName="mikrowarp" command="/usr/local/sbin/mikrowarp maintenance resume"
        $mikrowarpNativeLog text="Validating candidate forwarding before removing the previous container."
        $mikrowarpNativeAccept
    } do={
        $mikrowarpNativeLog text=("Candidate rejected: " . $err)
        $mikrowarpNativeAbort
        :error "Candidate rejected; previous image and state restored"
    }
    $mikrowarpNativeCommit
}
