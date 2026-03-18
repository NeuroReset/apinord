const http = require("http")

let domain = null
let pool = []

function genToken(){
return require("crypto").randomBytes(32).toString("hex")
}

function fillPool(){
while(pool.length < 50){
pool.push(genToken())
}
}

fillPool()

const server = http.createServer((req,res)=>{

```
if(req.url === "/health"){
    res.writeHead(200,{"Content-Type":"application/json"})
    return res.end(JSON.stringify({status:"ok"}))
}

if(req.url === "/status"){
    res.writeHead(200,{"Content-Type":"application/json"})
    return res.end(JSON.stringify({
        pool_size: pool.length,
        pool_target: 50
    }))
}

if(req.url === "/token"){
    if(pool.length === 0) fillPool()

    const token = pool.pop()

    res.writeHead(200,{"Content-Type":"application/json"})
    return res.end(JSON.stringify({
        success:true,
        gee_token:token,
        token_id:token.slice(0,8),
        pool_remaining:pool.length,
        elapsed_ms:5,
        age_ms:0,
        isOffline:true
    }))
}

if(req.url === "/config" && req.method === "POST"){
    let body=""
    req.on("data",c=>body+=c)
    req.on("end",()=>{
        try{
            const data=JSON.parse(body)
            domain=data.domain
        }catch(e){}
        res.writeHead(200,{"Content-Type":"application/json"})
        res.end(JSON.stringify({success:true}))
    })
    return
}

if(req.url === "/discovery" && req.method === "POST"){
    res.writeHead(200,{"Content-Type":"application/json"})
    return res.end(JSON.stringify({
        success:true,
        api_url:"https://api."+domain
    }))
}

res.writeHead(404)
res.end()
```

})

server.listen(3333,()=>{
console.log("token server listening on 3333")
})
