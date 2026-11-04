import io.ktor.http.*
import io.ktor.server.application.*
import io.ktor.server.cio.*
import io.ktor.server.engine.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.serialization.json.*
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

fun main() {
    val memos = ConcurrentHashMap<String, JsonObject>()
    val port = System.getenv("PORT").toInt()
    embeddedServer(CIO, host = "127.0.0.1", port = port) {
        routing {
            get("/health") { call.respondText("ready") }
            post("/api/memos") {
                val request = Json.parseToJsonElement(call.receiveText()).jsonObject
                val title = request.getValue("title").jsonPrimitive.content
                val body = request.getValue("body").jsonPrimitive.content
                val id = UUID.randomUUID().toString()
                val memo = buildJsonObject { put("id", id); put("title", title); put("body", body) }
                memos[id] = memo
                call.respondText(memo.toString(), ContentType.Application.Json, HttpStatusCode.Created)
            }
            get("/api/memos/{id}") {
                val memo = memos[call.parameters["id"]]
                if (memo == null) call.respond(HttpStatusCode.NotFound)
                else call.respondText(memo.toString(), ContentType.Application.Json, HttpStatusCode.OK)
            }
        }
    }.start(wait = true)
}
