$dest = "D:\Grey Matterz\Govt RFP\data\samples"
$headers = @{
    "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
$files = @{
    "mou_vvgnli_labour_2023.pdf"        = "https://vvgnli.gov.in/sites/default/files/2023-11/MoU%202023-24.pdf"
    "mou_mea_jordan_manpower.pdf"       = "https://www.mea.gov.in/images/pdf/mou-jordan.pdf"
    "mou_cbwe_workers_education.pdf"    = "https://dtnbwed.cbwe.gov.in/images/upload/Memorandum-of-Understanding-with-Ministry_GITF.pdf"
    "mou_dcmsme_textile.pdf"            = "https://dcmsme.gov.in/MoU%20bet%20DC%20MSME%20and%20Min%20of%20Textile.pdf"
    "mou_npc_kpmg.pdf"                  = "https://www.npcindia.gov.in/NPC/Files/MoUs/new/Signed%20MoU%20between%20NPC%20and%20KPMG15767.pdf"
    "eoi_upeida_consultant_ca.pdf"      = "https://upeida.up.gov.in/site/writereaddata/UploadNews/pdf/C_202401301421489528.pdf"
    "eoi_kerala_mission1000.pdf"        = "https://industry.kerala.gov.in/images/Schemes/MISSION1000-EOI/EOI_for_Empanelment_Kollam.pdf"
    "eoi_expert_consultants_2025.pdf"   = "https://cdnbbsr.s3waas.gov.in/s3cf05968255451bdefe3c5bc64d550517/uploads/2025/11/202511111701780551.pdf"
    "eoi_nimsme_empanelment.pdf"        = "https://www.nimsme.gov.in/media/tenders/EOI-for-empanelment-cdbm-dated-15-01-2026.pdf"
    "tender_mea_courier.pdf"            = "https://www.mea.gov.in/Portal/Tender/5996_1/1_Tendernotice_1-1.pdf"
    "tender_model_document_goods.pdf"   = "https://eprocure.gov.in/cppp/sites/default/files/standard_biddingdocs/MTD%20Goods%20NIC.pdf"
    "tender_tnpcb_tccl.pdf"             = "https://tnpcb.gov.in/PDF/Updates/Tenders/TenderTCCL16525.pdf"
    "tender_newmangalore_dredging.pdf"  = "https://newmangaloreport.gov.in/sites/default/files/2025-09/Mtcdredging2026-29TD.pdf"
    "agreement_sla_manpower_gem.pdf"    = "https://finance.py.gov.in/sites/default/files/SLAManpower_GeM.pdf"
    "agreement_transmission_service.pdf"= "https://powermin.gov.in/sites/default/files/uploads/Draft_sbd_tsa.pdf"
    "agreement_consultancy_template.pdf"= "https://www.startupindia.gov.in/content/dam/invest-india/Templates/public/Tools_templates/internal_templates/Lets_Venture/CONSULTANCY_AGREEMENT.pdf"
    "agreement_legalaffairs_contract.pdf" = "https://legalaffairs.gov.in/sites/default/files/Contract-Pravidhi_0.pdf"
    "circular_cbic_2015.pdf"            = "https://upload.indiacode.nic.in/showfile?actid=AC_CEN_2_2_00036_A1944-01_1671705649438&filename=circ1005-2015cx.pdf&type=circular"
    "circular_dopt_estt_2013.pdf"       = "https://documents.doptcirculars.nic.in/D2/D02est/22011_4_2013-Estt.D-08052017.pdf"
    "circular_pci_2014.pdf"             = "https://www.pci.nic.in/Circulars/14-2circular.pdf"
}

$results = @()
foreach ($name in $files.Keys) {
    $url = $files[$name]
    $out = Join-Path $dest $name
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -Headers $headers -TimeoutSec 25
        $bytes = [System.IO.File]::ReadAllBytes($out)
        $header = [System.Text.Encoding]::ASCII.GetString($bytes[0..3])
        if ($header -eq "%PDF") {
            $size = (Get-Item $out).Length
            $results += "OK   $name  ($size bytes)"
        } else {
            Remove-Item $out -Force
            $results += "BAD  $name  -> not a real PDF (got HTML/error page), removed"
        }
    } catch {
        $results += "FAIL $name  -> $($_.Exception.Message)"
    }
}
$results | ForEach-Object { Write-Output $_ }
