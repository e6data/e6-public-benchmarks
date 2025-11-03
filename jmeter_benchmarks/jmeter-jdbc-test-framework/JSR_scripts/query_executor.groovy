// Query executor - handles query selection and iteration
log.info("🔄 Query Executor starting...")

// Get loaded queries from setup
def queries = props.get("LOADED_QUERIES")
def queryCount = (props.get("QUERY_COUNT") ?: "0") as int

if (!queries || queryCount == 0) {
    log.error("❌ No queries loaded! Check setup thread execution.")
    vars.put("QUERY_ALIAS", "ERROR")
    vars.put("QUERY", "SELECT 'NO_QUERIES_LOADED' as error")
    return
}

// Get thread and iteration info
def threadNum = ctx.getThreadNum()
def iterationKey = "thread_${threadNum}_iteration"
def iterationNum = (props.get(iterationKey) ?: "0") as int

// Increment counter for next execution
props.put(iterationKey, (iterationNum + 1).toString())

// Select query based on recycling setting
def queryIndex = 0
def recycleOnEof = "true".equalsIgnoreCase(props.get("RECYCLE_ON_EOF"))

if (recycleOnEof) {
    // Cycle through queries
    queryIndex = iterationNum % queryCount
} else {
    // Sequential, stop at EOF
    queryIndex = iterationNum
    if (queryIndex >= queryCount) {
        log.info("🛑 EOF reached for thread ${threadNum}")
        throw new org.apache.jorphan.util.JMeterStopThreadException("EOF Reached")
    }
}

// Get the query
def selectedQuery = queries[queryIndex]
def queryAlias = selectedQuery.alias
def queryText = selectedQuery.query

// Set JMeter variables for the JDBC sampler
vars.put("QUERY_ALIAS", queryAlias)
vars.put("QUERY", queryText)

log.info("🎯 Thread ${threadNum}, Iteration ${iterationNum}: Selected '${queryAlias}' (${queryIndex}/${queryCount})")