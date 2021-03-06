##
## Utilities for computing RPKM
##
import os
import sys
import time

from collections import defaultdict

import subprocess

import rnaseqlib
import rnaseqlib.utils as utils

import pandas

import pysam


def load_sample_rpkms(sample,
                      rna_base):
    """
    Load RPKM tables for a sample. Return
    """
    rpkm_tables = {}
    for table_name in rna_base.rpkm_table_names:
        rpkm_table = None
        rpkm_filename = os.path.join(sample.rpkm_dir,
                                     "%s.rpkm" %(table_name))
        if os.path.isfile(rpkm_filename):
            # Insert the sample name into the header
            fieldnames = ["gene_id",
                          "rpkm_%s" %(sample.label),
                          "counts_%s" %(sample.label),
                          "exons"]
            # Load each table as a DataFrame
            rpkm_table = pandas.read_csv(rpkm_filename,
                                         sep="\t",
                                         names=fieldnames,
                                         # Skip the current header
                                         skiprows=1)
            # Add gene_symbol and gene_desc columns
            # to RPKM DataFrame
            gene_table = rna_base.gene_tables[table_name.split(".")[0]]
            gene_symbols = [gene_table.genes_to_names[gid] \
                            for gid in rpkm_table["gene_id"]]
            gene_descs = [gene_table.genes_to_desc[gid] \
                          for gid in rpkm_table["gene_id"]]
            rpkm_table["gene_symbol"] = gene_symbols
            rpkm_table["gene_desc"] = gene_descs
        else:
            print "WARNING: Cannot find RPKM filename %s" %(rpkm_filename)
        rpkm_tables[table_name] = rpkm_table
    return rpkm_tables
    

def output_rpkm(sample,
                output_dir,
                settings_info,
                rna_base,
                logger):
    """
    Output RPKM tables for the sample.

    Takes as input:

    - sample: a sample object
    - output_dir: output directory
    - settings_info: settings information
    - rna_base: an RNABase object
    """
    # Output RPKM information for all constitutive exon tables in the
    # in the RNA Base
    print "Outputting RPKM for: %s" %(sample.label)
    rpkm_tables = {}
    for table_name, const_exons in rna_base.tables_to_const_exons.iteritems():
        rpkm_output_filename = "%s.rpkm" %(os.path.join(output_dir,
                                                        table_name))
        rpkm_tables[table_name] = rpkm_output_filename
        if os.path.isfile(rpkm_output_filename):
            logger.info("  - Skipping RPKM output, found %s" \
                        %(rpkm_output_filename))
            continue
        # Directory where BAM containing mapping to constitutive
        # exons be stored
        bam2gff_outdir = os.path.join(output_dir,
                                      "bam2gff_const_exons")
        utils.make_dir(bam2gff_outdir)
        # Map reads to GFF of constitutive exons
        # Use the rRNA subtracted BAM file
        logger.info("Mapping BAM to GFF %s" %(const_exons.gff_filename))
        exons_bam_fname = map_bam2gff_subproc(logger,
                                              sample.ribosub_bam_filename,
                                              const_exons.gff_filename,
                                              bam2gff_outdir)
        # Compute RPKMs for sample: use number of ribosub mapped reads
        num_mapped = int(sample.qc.qc_results["num_ribosub_mapped"])
        if num_mapped == 0:
            logger.critical("Cannot compute RPKMs since sample %s has 0 " \
                            "mapped reads." %(sample.label))
            sys.exit(1)
        logger.info("Sample %s has %s mapped reads" %(sample.label, num_mapped))
        read_len = settings_info["readlen"]
        logger.info("Outputting RPKM from GFF aligned BAM (table %s)" \
                    %(table_name))
        output_rpkm_from_gff_aligned_bam(exons_bam_fname,
                                         num_mapped,
                                         read_len,
                                         const_exons,
                                         rpkm_output_filename)
    logger.info("Finished outputting RPKM for %s to %s" %(sample.label,
                                                          rpkm_output_filename))
    return rpkm_output_filename
    

def map_bam2gff_subproc(logger, bam_filename, gff_filename, output_dir,
                        interval_label="gff"):
    """
    Map BAM file against intervals in GFF, return results as BAM.

    Only keep hits that are in the interval.

    Uses tagBam utility from bedtools.
    """
    gff_basename = os.path.basename(gff_filename)
    bam_basename = os.path.basename(bam_filename)
    output_dir = os.path.join(output_dir, "bam2gff_%s" \
                              %(gff_basename))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    output_filename = os.path.join(output_dir, bam_basename)

    print "Mapping BAM to GFF..."
    print "  - BAM: %s" %(bam_filename)
    print "  - GFF: %s" %(gff_filename)
    print "  - Output file: %s" %(output_filename)
    if os.path.isfile(output_filename):
        print "WARNING: %s exists. Skipping.." \
              %(output_filename)
        return output_filename

    # Compile the tagBam command and pipe it to samtools to get
    # text, grep-able output
    tagBam = "tagBam"
    tagBam_cmd = \
        "%s -i %s -files %s -labels %s -intervals -f 1 | samtools view -h - " \
        %(tagBam, bam_filename, gff_filename,
          interval_label)
    print "Calling: %s" %(tagBam_cmd)
    if utils.which(tagBam) is None:
        logger.error("Aborting operation: tagBam not found.")
        sys.exit(1)
    # Call tagBam and check that it returned successfully
    print "Preparing to call tagBam..."
    tagBam_proc = subprocess.Popen(tagBam_cmd,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   shell=True)
    # BAM process
    print "Preparing to output results as BAM..."
    bam_cmd = "samtools view -Shb -o %s - " %(output_filename)
    print "BAM command: %s" %(bam_cmd)
    bam_proc = subprocess.Popen(bam_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE,
                                shell=True)
    # Iterate through the output of grep
    num_headers = 0
    num_hits = 0
    num_skipped_reads = 0
    for sam_read in tagBam_proc.stdout:
        # Skip reads that have no reference name
        sam_fields = sam_read.split("\t")
        read_name = sam_fields[0]
        if read_name == "":
            num_skipped_reads += 1
            continue
        gff_interval = ":%s:" %(interval_label)
        # If it's a header or a SAM read that matches a GFF interval,
        # pass it non to be converted to BAM
        if sam_read.startswith("@"):
            bam_proc.stdin.write(sam_read)
            num_headers += 1
        elif gff_interval in sam_read:
            if num_hits % 1000000 == 0:
                print "Through %d hits" %(num_hits)
            bam_proc.stdin.write(sam_read)
            num_hits += 1
    print "Skipped total of %d reads." %(num_skipped_reads)
    if num_headers == 0:
        # If no headers were found even, something must have failed
        # at the tagBam call.
        logger.error("tagBam call failed.")
        logger.error("tagBam error code: %d" %(tagBam_retval)) 
        sys.exit(1)
    if num_hits == 0:
        # If there were headers present but no hits, no read
        # must have mapped to the GFF intervals
        logger.warning("tagBam did not yield hits in GFF intervals. " \
                     "Found %d headers in BAM file. Do your headers in the GFF " \
                     "file match the headers of the BAM?" \
                     %(num_headers))
    tagBam_retval = tagBam_proc.wait()
    # Read the output of BAM proc
    bam_results = bam_proc.communicate()
    if bam_proc.returncode != 0:
        if "truncated" in bam_results[0]:
            logger.warning("Truncated BAM file produced by tagBam. " \
                           "This occurs if the BAM is empty because no " \
                           "read matched the GFF intervals.")
        else:
            logger.error("Conversion of tagBam hits to BAM failed.")
            logger.error("Output was %s" %(bam_results[0]))
            sys.exit(1)
    return output_filename

    
def output_rpkm_from_gff_aligned_bam(bam_filename,
                                     num_mapped,
                                     read_len,
                                     const_exons,
                                     output_filename,
                                     rpkm_header=["gene_id",
                                                  "rpkm",
                                                  "counts",
                                                  "exons"],
                                     na_val="NA"):
    """
    Given a BAM file aligned by bedtools (with 'gff' field),
    compute RPKM for each region, incorporating relevant
    optional fields from gff.

    Takes as input:

     - bam_filename: the BAM file
     - num_mapped: number of mapped reads to normalize to
     - read_len: read length
     - const_exons: Constitutive exons object
     - output_filename: output filename
    """
    bam_file = pysam.Samfile(bam_filename, "rb")
    print "Computing RPKM from BAM aligned to GFF..."
    print "  - BAM: %s" %(bam_filename)
    print "  - Output filename: %s" %(output_filename)
    # Map of gff region to read counts
    region_to_count = defaultdict(int)    
    for bam_read in bam_file:
        # Read aligns to region of interest
        gff_aligned_regions = None
        try:
            gff_aligned_regions = bam_read.opt("YB")
        except KeyError:
            continue
        parsed_regions = gff_aligned_regions.split("gff:")[1:]
        # Compile region counts and lengths
        for region in parsed_regions:
            region_chrom, coord_field = region.split(",")[0].split(":")[0:2]
            # Region internally converted to 0-based start, so we must add 1
            # to get it back
            region_start, region_end = map(int, coord_field.split("-"))
            region_start += 1
            region_str = "%s:%s-%s" %(region_chrom,
                                      str(region_start),
                                      str(region_end))
            # Count reads in region
            region_to_count[region_str] += 1
    # For each gene, find its exons. Sum their counts
    # and length to compute RPKM
    rpkm_table = []
    for gene_info in const_exons.genes_to_exons:
        gene_id = gene_info["gene_id"]
        exons = gene_info["exons"]
        if exons == na_val:
            continue
        parsed_exons = exons.split(",")
        # Strip the strand of the exons
        strandless_exons = []
        for parsed_exon in parsed_exons:
            curr_exon = parsed_exon[0:-2]
            if "." in curr_exon:
                # Strip off dot prefix if any is there
                curr_exon = curr_exon.split(".")[1]
            strandless_exons.append(curr_exon)
        curr_counts = [region_to_count[s_exon] for s_exon in strandless_exons]
        sum_counts = sum(curr_counts)
        curr_lens = [const_exons.exon_lens[exon] for exon in parsed_exons]
        sum_lens = sum(curr_lens)
        assert(len(curr_counts) == len(curr_lens)), \
            "Error: sum_counts != sum_lens in RPKM computation."
        gene_rpkm = compute_rpkm(sum_counts, sum_lens, num_mapped)
        # RPKM entry for gene
        rpkm_entry = {"rpkm": gene_rpkm,
                      "gene_id": gene_id,
                      "counts": sum_counts,
                      "exons": exons}
        rpkm_table.append(rpkm_entry)
    rpkm_df = pandas.DataFrame(rpkm_table)
    rpkm_df.to_csv(output_filename,
                   cols=rpkm_header,
                   na_rep=na_val,
                   sep="\t",
                   # 4-decimal point RPKM format
                   # Not compatible with current pandas versions
                   #float_format="%.4f",
                   index=False)
    return output_filename


def compute_rpkm(region_count,
                 region_len,
                 num_total_reads):
    """
    Compute RPKM for a region.
    """
    # Get length of region in KB
    region_kb = region_len / float(1e3)

    # Numerator of RPKM: reads per kilobase
    rpkm_num = (region_count / region_kb)

    # Denominator of RPKM: per M mapped reads
    num_reads_per_million = num_total_reads / float(1e6)

    rpkm = (rpkm_num / num_reads_per_million)
    return rpkm


def loess_normalize_table(rpkm_table, sample_pairs, prefix="norm"):
    """
    Compute loess pairwise comparisons for the given RPKM table
    across the pairs in 'sample_pairs'. Use 'prefix' as the
    name of the new column in the DataFrame.
    """
    if not utils.is_rpy2_available():
        # If rpy2 isn't available, quit
        return None
    # Use Rpy2 to do the normalization
    import rnaseqlib.stats.rpy2_utils as rpy2_utils
    
    for sample1, sample2 in sample_pairs:
        # Do loess-normalization between the samples
        # Compute the normalized values for this sample comparison
        # as well as the fold change
        # Normalized value for sample1
        sample1_col = "norm_%s.%s_1" %(sample1, sample2)
        # Normalized value for sample2
        sample2_col = "norm_%s.%s_2" %(sample1, sample2)
        # Normalized fold change
        fc_col = "norm_fc_%s.%s" %(sample1, sample2)
        sample1_vals = rpkm_table[sample1]
        sample2_vals = rpkm_table[sample2]
        # Get MA-normalized values 
        sample1_normed, sample2_normed = \
            rpy2_utils.run_ma_loess(sample1_vals.values,
                                    sample2_vals.values)
        rpkm_table[sample1_col] = sample1_normed
        rpkm_table[sample2_col] = sample2_normed
        # Compute fold change with normalized values
        rpkm_table[fc_col] = sample1_normed / sample2_normed
    return rpkm_table


    

